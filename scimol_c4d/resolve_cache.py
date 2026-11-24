"""Small, disposable cache for successful resolve responses only."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from scimol_c4d.records import record_integrity, validate_record


VERSION = 1
TTL_SECONDS = 7 * 24 * 60 * 60
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_FILES = 128
MAX_TOTAL_BYTES = 32 * 1024 * 1024
PREFIX = "resolve-v1-"
THUMBNAILS = ("thumbnail", "themed_thumbnail", "transparent_thumbnail",
              "transparent_dark_thumbnail")


def cache_path(cache_dir: Path, kind: str, text: str) -> Path:
    identity = json.dumps([VERSION, kind, text.strip()], ensure_ascii=False,
                          separators=(",", ":"))
    return cache_dir / (PREFIX + hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json")


def _valid_records(records: object, cache_dir: Path, kind: str, text: str) -> bool:
    if not isinstance(records, list) or not 1 <= len(records) <= 9:
        return False
    for record in records:
        if not isinstance(record, dict) or not record.get("record_integrity"):
            return False
        source = record.get("source")
        if not isinstance(source, dict):
            return False
        source_kind = source.get("kind")
        if kind == "smiles":
            matching = source_kind == "smiles" and source.get("input") == text
        elif kind == "formula":
            matching = source_kind == "pubchem" and source.get("query") == text
        elif kind in ("name", "auto"):
            matching = ((source_kind == "pubchem" and source.get("query") == text)
                        or (source_kind == "builtin_alias" and source.get("alias") == text)
                        or (kind == "auto" and source_kind == "smiles" and source.get("input") == text))
        else:
            matching = False
        if not matching:
            return False
        try:
            validate_record(record)
            if record_integrity(record) != record["record_integrity"]:
                return False
            for field in THUMBNAILS:
                value = record.get(field)
                if not isinstance(value, str):
                    return False
                image = Path(value)
                if image.suffix.lower() != ".png" or image.is_symlink():
                    return False
                if image.resolve().parent != cache_dir or not image.is_file():
                    return False
        except (OSError, ValueError, TypeError):
            return False
    return True


def load(cache_dir: Path, kind: str, text: str) -> list[dict] | None:
    path = cache_path(cache_dir, kind, text)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ENTRY_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        stamp = payload.get("created")
        if (payload.get("version") != VERSION or payload.get("kind") != kind
                or payload.get("text") != text.strip()
                or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not 0 <= time.time() - stamp <= TTL_SECONDS):
            return None
        records = payload.get("records")
        return records if _valid_records(records, cache_dir, kind, text.strip()) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _prune(cache_dir: Path) -> None:
    entries = []
    for path in cache_dir.glob(PREFIX + "*.json"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            entries.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue
    entries.sort(reverse=True)
    total = 0
    for index, (_, size, path) in enumerate(entries):
        total += size
        if index >= MAX_FILES or total > MAX_TOTAL_BYTES:
            try:
                path.unlink()
            except OSError:
                pass


def save(cache_dir: Path, kind: str, text: str, records: list[dict]) -> None:
    if not _valid_records(records, cache_dir, kind, text.strip()):
        return
    payload = {"version": VERSION, "kind": kind, "text": text.strip(),
               "created": time.time(), "records": records}
    try:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_ENTRY_BYTES:
            return
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_path(cache_dir, kind, text)
        # Do not replace a link supplied by another process or user.
        if path.is_symlink():
            return
        fd, name = tempfile.mkstemp(prefix=PREFIX, suffix=".tmp", dir=cache_dir)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        _prune(cache_dir)
    except (OSError, ValueError, TypeError):
        pass  # Cache failures must not fail a successful search.
