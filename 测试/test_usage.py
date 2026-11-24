"""Usage ranking and durable store behavior without C4D or RDKit."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scimol_c4d.records import record_integrity, validate_record
from scimol_c4d.usage import MAX_ITEMS, UsageStore


def molecule(index):
    smiles = "C" * (index + 1)
    record = {"schema_version": 1, "name": "结构 " + str(index), "smiles": smiles,
              "structure_key": hashlib.sha256(smiles.encode()).hexdigest(),
              "atoms": [{"id": 0, "element": "C", "x": float(index), "y": 0.0,
                         "z": 0.0}], "bonds": [], "coordinates_ready": True,
              "thumbnail_atom_positions": {"0": [23.0, 31.0]},
              "thumbnail_size": [360, 280]}
    record["record_integrity"] = record_integrity(record)
    return record


class UsageStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = UsageStore(Path(self.temp.name))

    def test_ranking_merges_used_records_and_keeps_unused_seed_order(self):
        seeds = [molecule(i) for i in range(4)]
        originals = copy.deepcopy(seeds)
        with patch("scimol_c4d.usage.time.time", side_effect=[10.0, 20.0, 30.0, 40.0]):
            self.store.record_use(seeds[2])
            self.store.record_use(seeds[1])
            self.store.record_use(seeds[2])
            self.store.record_use(molecule(4))
        ranked = self.store.ranked(seeds)
        self.assertEqual([item["name"] for item in ranked],
                         ["结构 2", "结构 4", "结构 1", "结构 0", "结构 3"])
        self.assertEqual([item["usage_count"] for item in ranked], [2, 1, 1, 0, 0])
        self.assertEqual(seeds, originals)
        for record in ranked:
            self.assertEqual(record["thumbnail_atom_positions"], {"0": [23.0, 31.0]})
            self.assertEqual([atom["id"] for atom in record["atoms"]], [0])
            self.assertEqual(validate_record(record)["record_integrity"], record["record_integrity"])

    def test_repeated_use_persists_across_instances(self):
        record = molecule(2)
        self.assertEqual(self.store.record_use(record), 1)
        self.assertEqual(UsageStore(self.temp.name).record_use(record), 2)
        ranked = UsageStore(self.temp.name).ranked([])
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["usage_count"], 2)
        self.assertEqual(record["record_integrity"], ranked[0]["record_integrity"])

    def test_store_caps_distinct_structures_at_one_hundred(self):
        with patch("scimol_c4d.usage.time.time", side_effect=[float(i + 1) for i in range(MAX_ITEMS + 3)]):
            for index in range(MAX_ITEMS + 3):
                self.store.record_use(molecule(index))
        stored = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(len(stored["items"]), MAX_ITEMS)
        names = [item["name"] for item in self.store.ranked([])]
        self.assertEqual(names[0], "结构 102")
        self.assertNotIn("结构 0", names)

    def test_corrupt_json_is_not_overwritten(self):
        bad = b'{"schema_version":1,"items": [broken]}'
        self.store.path.write_bytes(bad)
        with self.assertRaisesRegex(ValueError, "JSON"):
            self.store.record_use(molecule(0))
        with self.assertRaisesRegex(ValueError, "JSON"):
            self.store.ranked([molecule(0)])
        self.assertEqual(self.store.path.read_bytes(), bad)


if __name__ == "__main__":
    unittest.main()
