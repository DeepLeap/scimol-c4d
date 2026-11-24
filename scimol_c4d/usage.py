"""Local usage ranking for portable molecule records (no C4D dependency)."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time
import uuid

from .records import validate_record


MAX_ITEMS = 100
MAX_FILE_BYTES = 16 * 1024 * 1024


def _identity(record):
    """A saved display preset is distinct from its source molecule."""
    identifier = record.get("configuration_id")
    if identifier is not None:
        if (not isinstance(identifier, str) or not identifier.strip() or
                len(identifier) > 200 or identifier != identifier.strip()):
            raise ValueError("用户配置编号无效")
        return identifier
    return record["structure_key"]


class UsageStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / "常用次数.json"

    def _read_payload(self):
        if not self.path.is_file():
            return [], []
        if self.path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("常用次数文件过大")
        try:
            with self.path.open(encoding="utf-8-sig") as handle:
                value = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("常用次数文件无法读取或 JSON 已损坏") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("常用次数文件版本无效")
        items = value.get("items")
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise ValueError("常用次数条目无效")
        hidden = value.get("hidden", [])
        if (not isinstance(hidden, list) or len(hidden) > 5000 or
                any(not isinstance(key, str) or not key or len(key) > 200
                    for key in hidden) or len(set(hidden)) != len(hidden)):
            raise ValueError("隐藏条目无效")
        seen = set()
        result = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("常用次数条目无效")
            try:
                record = validate_record(item["record"])
                count = item["count"]
                last_used = item["last_used"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("常用次数条目无效") from exc
            if (not isinstance(count, int) or isinstance(count, bool) or count < 0 or
                    not isinstance(last_used, (int, float)) or isinstance(last_used, bool) or
                    not math.isfinite(last_used) or last_used < 0):
                raise ValueError("常用次数或使用时间无效")
            key = _identity(record)
            if key in seen:
                raise ValueError("常用次数存在重复条目")
            seen.add(key)
            result.append({"record": record, "count": count, "last_used": float(last_used)})
        return result, hidden

    def _read(self):
        return self._read_payload()[0]

    def _write(self, items, hidden):
        self.folder.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump({"schema_version": 1, "items": items,
                           "hidden": sorted(hidden)}, handle,
                          ensure_ascii=False, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def record_use(self, record):
        """Record one successful new-model creation; return its use count."""
        validated = validate_record(record)
        items, hidden = self._read_payload()  # Never replace a corrupt store.
        key = _identity(validated)
        now = time.time()
        current = next((item for item in items if _identity(item["record"]) == key), None)
        if current is None:
            current = {"record": validated, "count": 1, "last_used": now}
            items.append(current)
        else:
            current["record"] = validated
            current["count"] += 1
            current["last_used"] = now
        items.sort(key=lambda item: (-item["count"], -item["last_used"],
                                     _identity(item["record"])))
        hidden = [entry for entry in hidden if entry != key]
        self._write(items[:MAX_ITEMS], hidden)
        return current["count"]

    def remember(self, record):
        """Register or refresh a saved preset without counting model creation."""
        validated = validate_record(record)
        items, hidden = self._read_payload()
        key = _identity(validated)
        current = next((item for item in items if _identity(item["record"]) == key), None)
        if current is None:
            current = {"record": validated, "count": 0, "last_used": 0.0}
            items.append(current)
        else:
            current["record"] = validated
        items.sort(key=lambda item: (-item["count"], -item["last_used"],
                                     _identity(item["record"])))
        self._write(items[:MAX_ITEMS], [entry for entry in hidden if entry != key])
        return current["count"]

    def remove_records(self, records):
        """Remove usage and persistently hide those exact browser identities."""
        keys = {_identity(validate_record(record)) for record in records}
        if not keys:
            return 0
        items, hidden = self._read_payload()
        remaining = [item for item in items if _identity(item["record"]) not in keys]
        self._write(remaining, set(hidden) | keys)
        return len(items) - len(remaining)

    def ranked(self, seeds):
        """Merge seeds and usage records; unused seeds keep their input order."""
        items, hidden = self._read_payload()
        used = {_identity(item["record"]): item for item in items}
        seed_order = {}
        merged = {}
        for seed in seeds:
            record = validate_record(seed)
            key = _identity(record)
            if key in hidden:
                continue
            if key not in merged:
                seed_order[key] = len(seed_order)
                merged[key] = record
        for key, item in used.items():
            if key not in hidden:
                merged[key] = item["record"]
        ordered = sorted(merged, key=lambda key: (
            -used[key]["count"] if key in used else 0,
            -used[key]["last_used"] if key in used else 0,
            seed_order.get(key, len(seed_order)), key))
        result = []
        for key in ordered:
            record = merged[key]
            record["usage_count"] = used[key]["count"] if key in used else 0
            result.append(record)
        return result
