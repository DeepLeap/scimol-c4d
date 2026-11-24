"""Run chemistry in a hidden, cancellable project-local Python process."""

from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
import weakref

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".runtime" / "Scripts" / "python.exe"
WORKER = Path(__file__).with_name("chemistry_worker.py")
DATA = ROOT / "数据"
CACHE = DATA / "缩略图"
_LOG_MAX_BYTES = 256 * 1024
_LOG_KEEP_BYTES = 128 * 1024
_LOG_LOCK = threading.Lock()


def _terminate_process(process):
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
    except Exception:
        pass
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass


def _cleanup_box(box):
    if box and box[0] is not None:
        proc = box[0]
        box[0] = None
        _terminate_process(proc)


class _WorkerHandle:
    """Persistent chemistry worker wrapper with non-blocking stderr draining."""

    def __init__(self, process):
        self.process = process
        self.stderr_lines = deque(maxlen=100)
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name="SciMolWorkerStderr"
        )
        self._stderr_thread.start()

    def _drain_stderr(self):
        pipe = self.process.stderr
        if pipe is None:
            return
        try:
            for line in pipe:
                text = line.rstrip("\r\n")
                if text:
                    self.stderr_lines.append(text)
        except Exception:
            pass

    def alive(self):
        return self.process.poll() is None

    def flush_stderr(self, wait_timeout=0.15):
        if not self.alive() and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=wait_timeout)
        lines = []
        while self.stderr_lines:
            lines.append(self.stderr_lines.popleft())
        return "\n".join(lines)


class Backend:
    def __init__(self, persistent=True):
        self.results = queue.Queue()
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._process = None
        self._daemon = None
        self._cleanup_box = [None]
        self._finalizer = weakref.finalize(self, _cleanup_box, self._cleanup_box)
        self._closed = False
        self.persistent = bool(persistent)
        self.generation = 0

    def cancel(self):
        with self._lock:
            self.generation += 1
            process = self._process
            self._process = None
            if process is not None and self._daemon is not None and self._daemon.process is process:
                self._daemon = None
                self._cleanup_box[0] = None
        if process is not None:
            _terminate_process(process)

    def close(self):
        with self._lock:
            self._closed = True
            self.generation += 1
            busy = self._process
            daemon = self._daemon.process if self._daemon is not None else None
            self._process = None
            self._daemon = None
            self._cleanup_box[0] = None
        _terminate_process(busy)
        if daemon is not None and daemon is not busy:
            _terminate_process(daemon)

    def submit(self, payload, context=None):
        self.cancel()
        with self._lock:
            if self._closed:
                return self.generation
            token = self.generation
        request = dict(payload, cache_dir=str(CACHE))
        thread = threading.Thread(target=self._run, args=(token, request, context), daemon=True)
        thread.start()
        return token

    def _spawn_process(self, persistent):
        args = [str(PYTHON), str(WORKER)]
        if persistent:
            args.append("--worker-loop")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        return subprocess.Popen(
            args, cwd=str(ROOT),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1 if persistent else -1,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _run(self, token, request, context):
        start = time.monotonic()
        if not self.persistent:
            self._run_oneshot(token, request, context, start)
            return
        with self._lock:
            if self._closed or token != self.generation:
                return
        with self._io_lock:
            with self._lock:
                if self._closed or token != self.generation:
                    return
            handle = None
            timer = None
            timed_out = threading.Event()
            try:
                if not PYTHON.is_file():
                    raise RuntimeError("缺少化学运行环境，请先运行安装运行环境.ps1")
                CACHE.mkdir(parents=True, exist_ok=True)
                with self._lock:
                    if self._closed or token != self.generation:
                        return
                    handle = self._daemon
                    if handle is None or not handle.alive():
                        if handle is not None:
                            _terminate_process(handle.process)
                        proc = self._spawn_process(persistent=True)
                        handle = _WorkerHandle(proc)
                        self._daemon = handle
                        self._cleanup_box[0] = proc
                    self._process = handle.process

                def _abort_timeout():
                    with self._lock:
                        if self._process is not handle.process or token != self.generation:
                            return
                        timed_out.set()
                        if self._daemon is handle:
                            self._daemon = None
                            self._cleanup_box[0] = None
                    _terminate_process(handle.process)

                timer = threading.Timer(90.0, _abort_timeout)
                timer.daemon = True
                timer.start()

                payload_line = json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n"
                handle.process.stdin.write(payload_line)
                handle.process.stdin.flush()
                line = handle.process.stdout.readline()

                if timed_out.is_set():
                    raise RuntimeError("处理超时，请减少结构数量后重试")
                with self._lock:
                    if self._closed or token != self.generation:
                        return
                if not line:
                    with self._lock:
                        if self._daemon is handle:
                            self._daemon = None
                            self._cleanup_box[0] = None
                    stderr_text = handle.flush_stderr(wait_timeout=0.3)
                    _terminate_process(handle.process)
                    if stderr_text:
                        self._log(stderr_text)
                    raise RuntimeError("化学处理进程失败，请查看运行日志")
                result = json.loads(line)
                if not isinstance(result, dict) or "ok" not in result:
                    raise RuntimeError("化学处理返回格式无效")
                stderr_text = handle.flush_stderr(wait_timeout=0.0)
                if stderr_text:
                    self._log(stderr_text)
            except Exception as exc:
                if timed_out.is_set():
                    exc = RuntimeError("处理超时，请减少结构数量后重试")
                with self._lock:
                    cancelled = self._closed or token != self.generation
                if cancelled:
                    return
                if handle is not None and not handle.alive():
                    with self._lock:
                        if self._daemon is handle:
                            self._daemon = None
                            self._cleanup_box[0] = None
                    stderr_text = handle.flush_stderr(wait_timeout=0.2)
                    if stderr_text:
                        self._log(stderr_text)
                result = {"ok": False, "error": str(exc)}
                self._log(str(exc))
            finally:
                if timer is not None:
                    timer.cancel()
                with self._lock:
                    if handle is not None and self._process is handle.process:
                        self._process = None
            with self._lock:
                if self._closed or token != self.generation:
                    return
            self.results.put((token, context, result, time.monotonic() - start))

    def _run_oneshot(self, token, request, context, start):
        process = None
        try:
            if not PYTHON.is_file():
                raise RuntimeError("缺少化学运行环境，请先运行安装运行环境.ps1")
            CACHE.mkdir(parents=True, exist_ok=True)
            process = self._spawn_process(persistent=False)
            with self._lock:
                if self._closed or token != self.generation:
                    _terminate_process(process)
                    return
                self._process = process
            try:
                stdout, stderr = process.communicate(
                    json.dumps(request, ensure_ascii=False, allow_nan=False), timeout=90
                )
            except subprocess.TimeoutExpired:
                _terminate_process(process)
                raise RuntimeError("处理超时，请减少结构数量后重试")
            if stderr:
                self._log(stderr)
            if process.returncode != 0:
                raise RuntimeError("化学处理进程失败，请查看运行日志")
            result = json.loads(stdout)
            if not isinstance(result, dict) or "ok" not in result:
                raise RuntimeError("化学处理返回格式无效")
        except Exception as exc:
            with self._lock:
                if self._closed or token != self.generation:
                    return
            result = {"ok": False, "error": str(exc)}
            self._log(str(exc))
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
        with self._lock:
            if self._closed or token != self.generation:
                return
        self.results.put((token, context, result, time.monotonic() - start))

    @staticmethod
    def _log(message):
        if not message:
            return
        with _LOG_LOCK:
            DATA.mkdir(parents=True, exist_ok=True)
            log_path = DATA / "运行日志.txt"
            try:
                if log_path.is_file() and log_path.stat().st_size > _LOG_MAX_BYTES:
                    raw = log_path.read_bytes()
                    tail = raw[-_LOG_KEEP_BYTES:]
                    newline = tail.find(b"\n")
                    if 0 <= newline < len(tail) - 1:
                        tail = tail[newline + 1:]
                    temp = log_path.with_name(f"{log_path.name}.{uuid.uuid4().hex}.tmp")
                    try:
                        temp.write_bytes(tail)
                        os.replace(temp, log_path)
                    finally:
                        if temp.exists():
                            temp.unlink()
            except OSError:
                pass
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(message)[-6000:] + "\n")
