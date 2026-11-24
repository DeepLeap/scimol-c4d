"""Offline suggestion ranking and local name resolution."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scimol_c4d import chemistry_worker
from scimol_c4d.search_index import suggest_names


class SearchTests(unittest.TestCase):
    def test_benzene_ring_suggests_benzene_then_related_structures(self):
        names = suggest_names("苯环")
        self.assertEqual(names[0], "苯")
        self.assertIn("苯酚", names)
        self.assertIn("邻二甲苯", names)
        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual(len(names), 8)

    def test_exact_alias_and_partial_name_stay_local(self):
        self.assertEqual(suggest_names("酒精")[0], "乙醇")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(chemistry_worker, "_network", side_effect=AssertionError("network called")):
                records = chemistry_worker._resolve({"kind": "name", "text": "苯环"}, Path(directory))
                self.assertEqual(records[0]["name"], "苯")
                self.assertGreater(len(records), 1)
                self.assertEqual(records[0]["source"]["alias"], "苯环")

    def test_unmatched_english_name_keeps_pubchem_path(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(chemistry_worker, "_pubchem_cids", return_value=[2244]) as cids:
                with patch.object(chemistry_worker, "_pubchem_names", return_value={}):
                    with patch.object(chemistry_worker, "_pubchem_records", return_value=[]) as records:
                        chemistry_worker._resolve({"kind": "name", "text": "aspirin"}, Path(directory))
        cids.assert_called_once_with("name", "aspirin")
        records.assert_called_once()


if __name__ == "__main__":
    unittest.main()
