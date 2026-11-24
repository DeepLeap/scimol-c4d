"""Portable, atomically saved local molecule favorites."""

import copy
import base64
import json
import os
from pathlib import Path
import shutil
import struct
import time
import uuid

from .records import normalized_style, validate_record


class Library:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / "收藏.json"

    @staticmethod
    def _read_payload(path):
        if not Path(path).is_file():
            return [], []
        if Path(path).stat().st_size > 16 * 1024 * 1024:
            raise ValueError("收藏文件过大")
        with Path(path).open(encoding="utf-8-sig") as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("收藏文件版本无效")
        folders = value.get("folders", [])
        if (not isinstance(folders, list) or len(folders) > 1000 or
                any(not isinstance(name, str) or not name.strip() or
                    len(name) > 100 or name != name.strip() for name in folders) or
                len(folders) != len(set(folders))):
            raise ValueError("收藏文件夹无效")
        items = value.get("items")
        if not isinstance(items, list) or len(items) > 1000:
            raise ValueError("收藏数量无效")
        result = []
        seen_ids = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("收藏条目无效")
            entry = copy.deepcopy(item)
            entry["record"] = validate_record(entry["record"])
            entry["style"] = normalized_style(entry.get("style"))
            entry["label"] = str(entry.get("label") or entry["record"]["name"])[:300]
            entry["category"] = str(entry.get("category", "未分类"))[:100]
            if entry.get("type") == "configuration":
                identifier = entry.get("id")
                if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
                    raise ValueError("用户配置编号无效或重复")
                if entry["record"].get("configuration_id") != identifier:
                    raise ValueError("用户配置编号与结构记录不一致")
            seen_ids.add(entry.get("id"))
            result.append(entry)
        return result, folders

    @staticmethod
    def _read(path):
        return Library._read_payload(path)[0]

    def all(self):
        return self._read(self.path)

    def folders(self):
        """Include the default folder, empty folders and legacy categories."""
        items, declared = self._read_payload(self.path)
        return list(dict.fromkeys(["未分类", *declared,
                                   *(item["category"] for item in items)]))

    @staticmethod
    def _folder_name(name):
        if (not isinstance(name, str) or not name.strip() or
                len(name.strip()) > 100 or any(ord(char) < 32 for char in name)):
            raise ValueError("文件夹名称无效")
        return name.strip()

    def create_folder(self, name):
        name = self._folder_name(name)
        items, folders = self._read_payload(self.path)
        if name in self.folders():
            raise ValueError("文件夹已存在")
        folders.append(name)
        self._write(items, folders=folders)

    def rename_folder(self, old, new):
        old, new = self._folder_name(old), self._folder_name(new)
        items, folders = self._read_payload(self.path)
        if old not in self.folders() or old == "未分类":
            raise ValueError("文件夹不存在或不可重命名")
        if new != old and new in self.folders():
            raise ValueError("文件夹已存在")
        if new == old:
            return
        folders = [new if name == old else name for name in folders]
        if old not in folders and new not in folders:
            folders.append(new)
        for item in items:
            if item["category"] == old:
                item["category"] = new
        self._write(items, folders=folders)

    def rename_item(self, key, label):
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 300:
            raise ValueError("收藏名称无效")
        items, folders = self._read_payload(self.path)
        match = next((item for item in items if item.get("id") == key), None)
        if match is None:
            match = next((item for item in items if item.get("type") != "configuration" and
                          item["record"]["structure_key"] == key), None)
        if match is not None:
            match["label"] = label.strip()
            self._write(items, folders=folders)
            return match
        raise ValueError("收藏条目不存在")

    def _write(self, items, path=None, folders=None):
        target = Path(path or self.path)
        if folders is None:
            folders = self._read_payload(self.path)[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump({"schema_version": 1, "folders": folders, "items": items},
                          handle, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()

    def save(self, record, style, label="", category="未分类"):
        record = validate_record(record)
        style = normalized_style(style)
        thumbnail = Path(record.get("thumbnail", ""))
        if thumbnail.is_file() and thumbnail.suffix.lower() == ".png":
            image_folder = self.folder / "收藏缩略图"
            image_folder.mkdir(parents=True, exist_ok=True)
            target = image_folder / (record["structure_key"] + ".png")
            if thumbnail.resolve() != target.resolve():
                shutil.copy2(thumbnail, target)
            record["thumbnail"] = str(target)
        items, folders = self._read_payload(self.path)
        category = self._folder_name(category or "未分类")
        if category != "未分类" and category not in folders:
            folders.append(category)
        key = record["structure_key"]
        entry = {"id": key, "label": (label.strip() or record["name"])[:300],
                 "category": category,
                 "record": record, "style": style, "saved_at": int(time.time())}
        existing = next((index for index, item in enumerate(items)
                         if item.get("type") != "configuration" and
                         item["record"]["structure_key"] == key), None)
        if existing is None:
            items.append(entry)
        else:
            items[existing] = entry
        self._write(items, folders=folders)
        return entry

    def save_configuration(self, record, style, label, category="未分类",
                           configuration_id=None):
        """Save a distinct display preset without changing the molecule source."""
        record = validate_record(record)  # Deep copy; never rewrite worker atoms.
        style = normalized_style(style)
        thumbnail = Path(record.get("thumbnail", ""))
        if thumbnail.is_file() and thumbnail.suffix.lower() == ".png":
            image_folder = self.folder / "收藏缩略图"
            image_folder.mkdir(parents=True, exist_ok=True)
            target = image_folder / (record["structure_key"] + ".png")
            if thumbnail.resolve() != target.resolve():
                shutil.copy2(thumbnail, target)
            record["thumbnail"] = str(target)
        category = self._folder_name(category or "未分类")
        items, folders = self._read_payload(self.path)
        if category != "未分类" and category not in folders:
            folders.append(category)
        if configuration_id is None:
            identifier = str(uuid.uuid4())
            while any(item.get("id") == identifier for item in items):
                identifier = str(uuid.uuid4())
            base = str(label or "").strip() or record["name"]
            base = base[:300]
            names = {item["label"] for item in items if item["category"] == category}
            name = base
            suffix = 1
            while name in names:
                marker = " %d" % suffix
                name = base[:300 - len(marker)] + marker
                suffix += 1
            entry = {"id": identifier, "type": "configuration", "label": name,
                     "category": category, "record": record, "style": style,
                     "saved_at": int(time.time())}
            items.append(entry)
        else:
            identifier = str(configuration_id)
            entry = next((item for item in items
                          if item.get("id") == identifier and
                          item.get("type") == "configuration"), None)
            if entry is None:
                raise ValueError("用户配置不存在")
            base = (str(label or "").strip() or entry["label"])[:300]
            names = {item["label"] for item in items if item["category"] == category
                     and item.get("id") != identifier}
            name, suffix = base, 1
            while name in names:
                marker = " %d" % suffix
                name = base[:300 - len(marker)] + marker
                suffix += 1
            entry.update(label=name,
                         category=category, record=record, style=style,
                         saved_at=int(time.time()))
        record["configuration_id"] = identifier
        self._write(items, folders=folders)
        return entry

    def remove(self, key):
        items, folders = self._read_payload(self.path)
        target = next((item for item in items if item.get("id") == key), None)
        if target is None:
            target = next((item for item in items
                           if item.get("type") != "configuration" and
                           item["record"]["structure_key"] == key), None)
        if target is not None:
            items.remove(target)
            self._write(items, folders=folders)

    def remove_many(self, keys):
        """Remove exact configuration IDs or legacy molecule keys in one write."""
        targets = set(keys)
        if any(not isinstance(key, str) or not key for key in targets):
            raise ValueError("收藏条目编号无效")
        if not targets:
            return 0
        items, folders = self._read_payload(self.path)
        remaining = [item for item in items if not (
            item.get("id") in targets if item.get("type") == "configuration"
            else item["record"]["structure_key"] in targets)]
        removed = len(items) - len(remaining)
        if removed:
            self._write(remaining, folders=folders)
        return removed

    def export_to(self, path):
        items, folders = self._read_payload(self.path)
        for item in items:
            thumbnail = Path(item["record"].get("thumbnail", ""))
            if thumbnail.is_file() and thumbnail.stat().st_size <= 256000:
                raw = thumbnail.read_bytes()
                if raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    item["thumbnail_png"] = base64.b64encode(raw).decode("ascii")
        self._write(items, path, folders=folders)

    def import_from(self, path):
        incoming, imported_folders = self._read_payload(path)
        existing, folders = self._read_payload(self.path)
        def identity(item):
            if item.get("type") == "configuration":
                return ("configuration", item["id"])
            return ("legacy", item["record"]["structure_key"])
        by_key = {identity(item): item for item in existing}
        images = {}
        for item in incoming:
            encoded = item.get("thumbnail_png")
            if encoded:
                if not isinstance(encoded, str) or len(encoded) > 350000:
                    raise ValueError("收藏缩略图过大")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                    width, height = struct.unpack(">II", raw[16:24])
                except (ValueError, struct.error) as exc:
                    raise ValueError("收藏缩略图无效") from exc
                if not raw.startswith(b"\x89PNG\r\n\x1a\n") or not (0 < width <= 1024 and 0 < height <= 1024):
                    raise ValueError("收藏缩略图无效")
                images[item["record"]["structure_key"]] = raw
        for item in incoming:
            identity_key = identity(item)
            if identity_key in by_key:
                continue
            key = item["record"]["structure_key"]
            # An imported record must not redirect image loading to arbitrary paths.
            item["record"]["thumbnail"] = ""
            for field in ("themed_thumbnail", "transparent_thumbnail", "transparent_dark_thumbnail"):
                item["record"].pop(field, None)
            # Externally imported records are rechecked and reconstructed by RDKit.
            item["record"]["coordinates_ready"] = False
            item["record"].pop("record_integrity", None)
            item.pop("thumbnail_png", None)
            if key in images:
                folder = self.folder / "收藏缩略图"
                folder.mkdir(parents=True, exist_ok=True)
                thumbnail = folder / (key + ".png")
                thumbnail.write_bytes(images[key])
                item["record"]["thumbnail"] = str(thumbnail)
            by_key[identity_key] = item
        folders = list(dict.fromkeys([*folders, *imported_folders,
                                     *(item["category"] for item in incoming
                                       if item["category"] != "未分类")]))
        self._write(list(by_key.values()), folders=folders)
        return len(by_key) - len(existing)
