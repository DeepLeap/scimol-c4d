"""Follow one independent C4D GeDialog with another on Windows.

Call the public functions on C4D's UI thread. The follower thread uses Win32
only; it never calls the C4D SDK or touches scene data.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys
import threading


GAP = 6
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000
POSITION_FLAGS = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS
MONITOR_DEFAULTTONEAREST = 2
GA_ROOT = 2


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    frame: Rect
    client_origin: tuple[int, int]
    class_name: str


class _NativeRect(ctypes.Structure):
    _fields_ = [(name, wintypes.LONG) for name in ("left", "top", "right", "bottom")]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _NativeRect),
                ("rcWork", _NativeRect), ("dwFlags", wintypes.DWORD)]


def _rect(value):
    return Rect(value.left, value.top, value.right, value.bottom)


def dialog_anchor(dialog):
    """Read a GeDialog's screen origin on the C4D UI thread."""
    point = dialog.Local2Screen()
    if not point or "x" not in point or "y" not in point:
        raise ValueError("GeDialog has no screen position yet")
    return int(point["x"]), int(point["y"])


def choose_window(windows, anchor, pid, title, workarea=None):
    """Require PID, exact title, and an SDK anchor near the client origin.

    A docked dialog's local origin is generally somewhere inside the large C4D
    main window. The size guard also rejects that window if near its corner.
    An ambiguous match is rejected rather than guessing an HWND.
    """
    matches = []
    for window in windows:
        if window.pid != pid or window.title != title:
            continue
        x, y = window.client_origin
        if abs(x - anchor[0]) > 48 or abs(y - anchor[1]) > 48:
            continue
        if workarea and window.frame.width >= workarea.width * 0.75 and window.frame.height >= workarea.height * 0.75:
            continue
        matches.append(window)
    return matches[0] if len(matches) == 1 else None


def follower_position(parent: Rect, child: Rect, workarea: Rect, gap=GAP):
    """Prefer the parent's right edge; keep the child usable on tight screens."""
    right_x = parent.right + gap
    left_x = parent.left - gap - child.width
    if right_x + child.width <= workarea.right:
        x = right_x
    elif left_x >= workarea.left:
        x = left_x
    else:
        # If no side fits, retain at least an 80 px grab area on the monitor.
        visible = min(80, max(1, child.width))
        x = min(max(right_x, workarea.left - child.width + visible), workarea.right - visible)
    if child.height <= workarea.height:
        y = min(max(parent.top, workarea.top), workarea.bottom - child.height)
    else:
        y = workarea.top
    return int(x), int(y)


class Win32Windows:
    """Small, process-local Win32 adapter. Construct only on Windows."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Floating GeDialog following requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u = self.user32
        u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.restype = ctypes.c_int
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_NativeRect)]
        u.GetWindowRect.restype = wintypes.BOOL
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(_NativeRect)]
        u.GetClientRect.restype = wintypes.BOOL
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.ClientToScreen.restype = wintypes.BOOL
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsWindow.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsIconic.restype = wintypes.BOOL
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromWindow.restype = wintypes.HANDLE
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
        u.GetMonitorInfoW.restype = wintypes.BOOL
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos.restype = wintypes.BOOL

    def _title(self, hwnd):
        size = self.user32.GetWindowTextLengthW(hwnd) + 1
        buffer = ctypes.create_unicode_buffer(size)
        self.user32.GetWindowTextW(hwnd, buffer, size)
        return buffer.value

    def window(self, hwnd):
        u = self.user32
        if (not u.IsWindow(hwnd) or not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd) or
                u.GetAncestor(hwnd, GA_ROOT) != hwnd):
            return None
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        frame = _NativeRect()
        client = _NativeRect()
        point = wintypes.POINT()
        if not (u.GetWindowRect(hwnd, ctypes.byref(frame)) and
                u.GetClientRect(hwnd, ctypes.byref(client)) and
                u.ClientToScreen(hwnd, ctypes.byref(point))):
            return None
        class_buffer = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        return Window(int(hwnd), int(pid.value), self._title(hwnd), _rect(frame),
                      (int(point.x), int(point.y)), class_buffer.value)

    def windows(self, pid):
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _):
            window = self.window(hwnd)
            if window and window.pid == pid:
                found.append(window)
            return True

        callback = callback_type(visit)
        self.user32.EnumWindows(callback, 0)
        return found

    def workarea(self, hwnd):
        monitor = self.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not monitor or not self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        return _rect(info.rcWork)

    def move(self, hwnd, x, y):
        return bool(self.user32.SetWindowPos(hwnd, None, x, y, 0, 0, POSITION_FLAGS))


def editor_open_position(browser_dialog, editor_width=520, editor_height=680,
                         title="分子资源库", native=None):
    """Return (xpos, ypos) for ``editor.Open``; None means use SDK default.

    Call only after the browser window is visible and from the C4D UI thread.
    """
    try:
        native = native or Win32Windows()
        anchor = dialog_anchor(browser_dialog)
        pid = os.getpid()
        windows = native.windows(pid)
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    # The workarea is read from each candidate's own monitor.
    candidates = []
    try:
        for window in windows:
            work = native.workarea(window.hwnd)
            if choose_window([window], anchor, pid, title, work):
                candidates.append((window, work))
    except (OSError, AttributeError):
        return None
    if len(candidates) != 1 or candidates[0][1] is None:
        return None
    parent, work = candidates[0]
    hypothetical = Rect(0, 0, editor_width, editor_height)
    return follower_position(parent.frame, hypothetical, work)


class WindowFollower:
    """Bounded Win32 polling; call start/stop from the C4D UI thread."""

    def __init__(self, native=None, interval=0.03):
        self.native = native
        self.interval = max(0.02, float(interval))
        self._stop = None
        self._thread = None
        self._identities = None

    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive() and
                    self._stop is not None and not self._stop.is_set())

    def start(self, browser_dialog, editor_dialog, browser_title="分子资源库",
              editor_title="结构详情"):
        if not self.stop():
            return False
        try:
            native = self.native or Win32Windows()
            pid = os.getpid()
            anchors = (dialog_anchor(browser_dialog), dialog_anchor(editor_dialog))
            windows = native.windows(pid)
        except (OSError, ValueError, TypeError, AttributeError):
            return False
        selected = []
        try:
            for anchor, title in zip(anchors, (browser_title, editor_title)):
                candidates = []
                for window in windows:
                    work = native.workarea(window.hwnd)
                    if work and choose_window([window], anchor, pid, title, work):
                        candidates.append(window)
                if len(candidates) != 1:
                    return False
                selected.append(candidates[0])
        except (OSError, AttributeError):
            return False
        if selected[0].hwnd == selected[1].hwnd:
            return False
        self.native = native
        self._identities = (selected[0], selected[1])
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop, self._identities, native),
                                        name="SciMolWindowFollower", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if self._stop is not None:
            self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=0.2)
            if thread.is_alive():
                # Keep the stop event and thread reachable. start() will retry
                # after this worker has actually exited.
                return False
        self._thread = None
        self._identities = None
        self._stop = None
        return True

    def _run(self, stop, identities, native):
        parent_id, child_id = identities
        last_target = None
        while not stop.wait(self.interval):
            parent = native.window(parent_id.hwnd)
            child = native.window(child_id.hwnd)
            if not (parent and child):
                break
            if (parent.hwnd == child.hwnd or
                    parent.pid != parent_id.pid or child.pid != child_id.pid or
                    parent.title != parent_id.title or child.title != child_id.title or
                    parent.class_name != parent_id.class_name or child.class_name != child_id.class_name):
                break
            work = native.workarea(parent.hwnd)
            if not work or not choose_window([parent], parent.client_origin, parent.pid, parent.title, work):
                break
            child_work = native.workarea(child.hwnd)
            if not child_work or not choose_window([child], child.client_origin, child.pid, child.title, child_work):
                break
            target = follower_position(parent.frame, child.frame, work)
            if (child.frame.left, child.frame.top) == target:
                last_target = target
                continue
            if target != last_target and not stop.is_set():
                if not native.move(child.hwnd, *target):
                    break
                last_target = target
        stop.set()
