"""Saved-preset identities and batch-management persistence without C4D."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from scimol_c4d.library import Library
from scimol_c4d.records import record_integrity
from scimol_c4d.usage import UsageStore


def molecule(smiles, name):
    record = {
        "schema_version": 1, "name": name, "smiles": smiles,
        "structure_key": hashlib.sha256(smiles.encode()).hexdigest(),
        "atoms": [{"id": 0, "element": "C", "x": 0.0, "y": 0.0, "z": 0.0}],
        "bonds": [], "coordinates_ready": True,
    }
    record["record_integrity"] = record_integrity(record)
    return record


class BrowserLibraryManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.library = Library(folder / "library")
        self.usage = UsageStore(folder / "usage")
        self.source = molecule("CCO", "乙醇")

    def test_same_graph_two_saved_presets_rank_separately_and_remember_is_zero_use(self):
        original = copy.deepcopy(self.source)
        large = self.library.save_configuration(self.source, {"atom_radius": .5}, "大球")
        small = self.library.save_configuration(self.source, {"atom_radius": .2}, "小球")
        self.assertEqual(self.usage.remember(large["record"]), 0)
        self.assertEqual(self.usage.remember(small["record"]), 0)
        self.assertEqual(self.usage.remember(large["record"]), 0)
        self.assertEqual(self.usage.record_use(small["record"]), 1)
        ranked = self.usage.ranked([self.source, large["record"], small["record"]])
        self.assertEqual([item.get("configuration_id") for item in ranked],
                         [small["id"], None, large["id"]])
        self.assertEqual([item["usage_count"] for item in ranked], [1, 0, 0])
        self.assertEqual(self.source, original)
        self.assertEqual(len(json.loads(self.usage.path.read_text(encoding="utf-8"))["items"]), 2)

    def test_removing_one_preset_preserves_original_and_other_preset(self):
        large = self.library.save_configuration(self.source, {}, "大球")
        small = self.library.save_configuration(self.source, {}, "小球")
        self.usage.remember(large["record"])
        self.usage.remember(small["record"])
        self.assertEqual(self.usage.remove_records([large["record"]]), 1)
        self.assertEqual(self.library.remove_many([large["id"]]), 1)
        ranked = self.usage.ranked([self.source, large["record"], small["record"]])
        self.assertEqual({item.get("configuration_id") for item in ranked},
                         {None, small["id"]})
        self.assertEqual([item["id"] for item in self.library.all()], [small["id"]])

    def test_hidden_builtin_persists_until_same_identity_is_reused(self):
        self.assertEqual(self.usage.remove_records([self.source]), 0)
        reloaded = UsageStore(self.usage.folder)
        self.assertEqual(reloaded.ranked([self.source]), [])
        self.assertIn(self.source["structure_key"],
                      json.loads(reloaded.path.read_text(encoding="utf-8"))["hidden"])
        self.assertEqual(reloaded.record_use(self.source), 1)
        self.assertEqual(reloaded.ranked([self.source])[0]["usage_count"], 1)
        self.assertEqual(reloaded.remove_records([self.source]), 1)
        self.assertEqual(reloaded.remember(self.source), 0)
        self.assertEqual(reloaded.ranked([self.source])[0]["usage_count"], 0)

    def test_batch_library_removal_keeps_folders_and_unrelated_entries(self):
        self.library.create_folder("空文件夹")
        legacy = self.library.save(self.source, {}, "乙醇", "科研")
        first = self.library.save_configuration(self.source, {}, "第一版", "科研")
        second = self.library.save_configuration(self.source, {}, "第二版", "科研")
        other = self.library.save(molecule("O", "水"), {}, "水", "未分类")
        self.assertEqual(self.library.remove_many([legacy["id"], first["id"], "missing"]), 2)
        self.assertEqual({item["id"] for item in self.library.all()},
                         {second["id"], other["id"]})
        self.assertEqual(self.library.folders(), ["未分类", "空文件夹", "科研"])
        self.assertEqual(self.library.remove_many([first["id"]]), 0)

    def test_corrupt_usage_payload_is_never_replaced_by_bulk_remove(self):
        self.usage.folder.mkdir(parents=True)
        self.usage.path.write_text('{"schema_version": 1, "items": [oops]}', encoding="utf-8")
        before = self.usage.path.read_bytes()
        with self.assertRaises(ValueError):
            self.usage.remove_records([self.source])
        self.assertEqual(self.usage.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
