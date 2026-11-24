"""Test the persistence boundary, not the C4D implementation."""

import hashlib
import importlib.util
import json
import copy
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scimol_c4d.backend import Backend
from scimol_c4d.library import Library
from scimol_c4d.records import validate_record

spec = importlib.util.spec_from_file_location("storage_chemistry_worker", PROJECT / "scimol_c4d" / "chemistry_worker.py")
chemistry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chemistry)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.library = Library(self.folder / "library")

    def tearDown(self):
        self.temp.cleanup()

    def molecule(self, smiles):
        record = chemistry.handle({"action": "resolve", "kind": "smiles", "text": smiles,
                                   "cache_dir": str(self.folder / "cache")})["records"][0]
        return chemistry.handle({"action": "generate", "record": record,
                                 "cache_dir": str(self.folder / "cache")})["record"]

    def test_same_formula_isomers_are_not_merged(self):
        self.library.save(self.molecule("CCO"), {}, "乙醇")
        self.library.save(self.molecule("COC"), {}, "二甲醚")
        self.assertEqual(len(self.library.all()), 2)
        self.assertEqual({item["record"]["formula"] for item in self.library.all()}, {"C2H6O"})

    def test_coordinates_and_original_unspecified_graph_survive_export(self):
        record = self.molecule("CC(O)C(=O)O")
        self.library.save(record, {"bond_mode": "single"}, "我的新分子", "自定义")
        path = self.folder / "backup.json"
        self.library.export_to(path)
        another = Library(self.folder / "another")
        another.import_from(path)
        entry = another.all()[0]
        self.assertEqual(entry["record"]["atoms"], record["atoms"])
        self.assertEqual(entry["record"]["graph_molblock"], record["graph_molblock"])
        self.assertEqual(entry["record"]["stereo_status"], "unspecified")
        self.assertEqual(entry["style"]["bond_mode"], "single")
        self.assertEqual(entry["label"], "我的新分子")

    def test_failed_atomic_write_preserves_previous_favorites(self):
        record = self.molecule("CCO")
        self.library.save(record, {})
        before = self.library.path.read_bytes()
        with patch("scimol_c4d.library.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.library.save(self.molecule("COC"), {})
        self.assertEqual(before, self.library.path.read_bytes())

    def test_damaged_import_does_not_erase_existing_library(self):
        self.library.save(self.molecule("CCO"), {})
        before = self.library.path.read_bytes()
        bad = self.folder / "bad.json"
        bad.write_text('{"schema_version":1,"items":[{"record":{}}]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.library.import_from(bad)
        self.assertEqual(before, self.library.path.read_bytes())

    def test_tampered_structure_identity_is_rejected(self):
        record = self.molecule("CCO")
        record["smiles"] = "COC"
        with self.assertRaises(ValueError):
            validate_record(record)

    def test_backend_replaces_cancelled_request(self):
        import scimol_c4d.backend as backend_mod
        backend = Backend()
        ctx_patch = patch.object(backend_mod, "PYTHON", Path(sys.executable)) if not backend_mod.PYTHON.is_file() else None
        if ctx_patch is not None:
            ctx_patch.start()
            self.addCleanup(ctx_patch.stop)
        self.addCleanup(backend.close)
        backend.submit({"action": "builtin"}, "old")
        token = backend.submit({"action": "resolve", "kind": "name", "text": "二甲苯"}, "new")
        result_token, context, result, elapsed = backend.results.get(timeout=15)
        self.assertEqual(result_token, token)
        self.assertEqual(context, "new")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["records"]), 3)
        backend.cancel()

    def test_cached_atoms_cannot_disagree_with_structure_image(self):
        record = self.molecule("CCO")
        oxygen = next(atom for atom in record["atoms"] if atom["element"] == "O")
        oxygen["element"] = "N"
        with self.assertRaisesRegex(ValueError, "数据已损坏"):
            validate_record(record)

    def test_exported_thumbnail_survives_moving_to_another_library(self):
        record = self.molecule("CCO")
        self.library.save(record, {}, "乙醇")
        path = self.folder / "portable.json"
        self.library.export_to(path)
        another = Library(self.folder / "portable_library")
        another.import_from(path)
        imported = another.all()[0]["record"]
        image = Path(imported["thumbnail"])
        self.assertTrue(image.is_file())
        self.assertTrue(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(image.is_relative_to(another.folder))
        self.assertFalse(imported["coordinates_ready"])

    def test_empty_folder_and_renames_survive_export_import(self):
        self.library.create_folder("待整理")
        self.library.create_folder("资料")
        record = self.molecule("CCO")
        self.library.save(record, {}, "乙醇", "待整理")
        self.library.rename_folder("待整理", "常用")
        self.library.rename_item(record["structure_key"], "酒精结构")
        backup = self.folder / "folders.json"
        self.library.export_to(backup)
        restored = Library(self.folder / "restored")
        restored.import_from(backup)
        self.assertEqual(restored.folders(), ["未分类", "常用", "资料"])
        self.assertEqual(restored.all()[0]["category"], "常用")
        self.assertEqual(restored.all()[0]["label"], "酒精结构")

    def test_schema_one_categories_remain_visible_as_folders(self):
        record = self.molecule("O")
        self.library.save(record, {}, category="旧分类")
        payload = json.loads(self.library.path.read_text(encoding="utf-8"))
        payload.pop("folders")
        self.library.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.library.folders(), ["未分类", "旧分类"])
        self.library.rename_folder("旧分类", "新分类")
        self.assertEqual(self.library.all()[0]["category"], "新分类")

    def test_invalid_folder_and_rename_do_not_change_file(self):
        self.library.create_folder("常用")
        before = self.library.path.read_bytes()
        with self.assertRaises(ValueError):
            self.library.create_folder("常用")
        with self.assertRaises(ValueError):
            self.library.rename_folder("未分类", "其他")
        with self.assertRaises(ValueError):
            self.library.rename_item("missing", "别名")
        self.assertEqual(self.library.path.read_bytes(), before)

    def test_configuration_save_as_update_and_name_suffix(self):
        record = self.molecule("CCO")
        original = copy.deepcopy(record)
        style = {"atom_radius": .42, "sphere_segments": 48,
                 "element_colors": {"O": [.2, .3, .4]},
                 "position_overrides": {"0": [1.0, 2.0, 3.0]},
                 "plane_groups": {"1": {"atom_ids": [0, 1],
                                        "origin": [0, 0, 0], "normal": [0, 0, 1]}}}
        first = self.library.save_configuration(record, style, "我的配置", "科研")
        second = self.library.save_configuration(record, {}, "我的配置", "科研")
        third = self.library.save_configuration(record, {}, "我的配置", "科研")
        self.assertEqual([item["label"] for item in self.library.all()],
                         ["我的配置", "我的配置 1", "我的配置 2"])
        self.assertEqual(len({first["id"], second["id"], third["id"]}), 3)
        self.assertEqual(record, original)
        self.assertEqual(first["record"]["atoms"], original["atoms"])
        self.assertEqual(first["record"]["configuration_id"], first["id"])
        self.assertEqual(first["style"]["position_overrides"], {"0": [1.0, 2.0, 3.0]})
        self.assertEqual(first["style"]["plane_groups"]["1"]["atom_ids"], [0, 1])
        self.assertEqual(first["style"]["element_colors"]["O"], [.2, .3, .4])
        updated = self.library.save_configuration(record, {"bond_radius": .12},
                                                   "更新版", "科研", first["id"])
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(len(self.library.all()), 3)
        self.assertEqual(self.library.all()[0]["style"]["bond_radius"], .12)
        self.assertEqual(self.library.all()[0]["label"], "更新版")
        renamed = self.library.save_configuration(record, {}, '我的配置 1', '科研', first['id'])
        self.assertEqual(renamed['label'], '我的配置 1 1')
        self.assertEqual(len(self.library.all()), 3)

    def test_configuration_id_rename_remove_and_legacy_key_compatibility(self):
        record = self.molecule("CCO")
        legacy = self.library.save(record, {}, "旧收藏")
        first = self.library.save_configuration(record, {}, "配置")
        second = self.library.save_configuration(record, {}, "配置")
        self.library.rename_item(second["id"], "第二份")
        self.assertEqual(next(item for item in self.library.all()
                              if item["id"] == second["id"])["label"], "第二份")
        self.library.remove(first["id"])
        self.assertEqual({item["id"] for item in self.library.all()},
                         {legacy["id"], second["id"]})
        self.library.remove(record["structure_key"])
        self.assertEqual([item["id"] for item in self.library.all()], [second["id"]])
        self.library.remove(record["structure_key"])
        self.assertEqual([item["id"] for item in self.library.all()], [second["id"]])

    def test_portable_import_keeps_distinct_configurations_of_same_molecule(self):
        record = self.molecule("CCO")
        self.library.save(record, {}, "旧收藏")
        first = self.library.save_configuration(record, {"atom_radius": .4}, "球大")
        second = self.library.save_configuration(record, {"atom_radius": .2}, "球小")
        backup = self.folder / "portable-configurations.json"
        self.library.export_to(backup)
        restored = Library(self.folder / "restored-configurations")
        self.assertEqual(restored.import_from(backup), 3)
        self.assertEqual(restored.import_from(backup), 0)
        entries = restored.all()
        self.assertEqual(len(entries), 3)
        self.assertEqual({entry["id"] for entry in entries if entry.get("type") == "configuration"},
                         {first["id"], second["id"]})
        self.assertEqual({entry["style"]["atom_radius"] for entry in entries
                          if entry.get("type") == "configuration"}, {.4, .2})
        self.assertTrue(all(entry["record"]["atoms"] == record["atoms"] for entry in entries))
        self.assertTrue(all(Path(entry["record"]["thumbnail"]).is_file() for entry in entries))


if __name__ == "__main__":
    unittest.main()
