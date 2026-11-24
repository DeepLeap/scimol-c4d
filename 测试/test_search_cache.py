"""Resolve cache behavior with a disposable thumbnail directory."""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scimol_c4d import chemistry_worker as worker, resolve_cache


class SearchCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()

    def request(self, kind="smiles", text="CCO"):
        return worker.handle({"action": "resolve", "kind": kind, "text": text,
                              "cache_dir": str(self.directory)})["records"]

    def test_second_search_skips_resolve_and_drawing(self):
        first = self.request()
        with patch.object(worker, "_resolve", side_effect=AssertionError("resolved again")), \
             patch.object(worker, "_thumbnail", side_effect=AssertionError("redrawn")), \
             patch.object(worker, "_network", side_effect=AssertionError("network")):
            self.assertEqual(self.request(), first)

    def test_result_survives_worker_process_restart(self):
        request = {"action": "resolve", "kind": "smiles", "text": "CCO",
                   "cache_dir": str(self.directory)}
        result = subprocess.run([sys.executable, str(Path(worker.__file__))],
                                input=json.dumps(request), capture_output=True,
                                text=True, encoding="utf-8", check=True)
        first = json.loads(result.stdout)["records"]
        with patch.object(worker, "_resolve", side_effect=AssertionError("resolved again")):
            self.assertEqual(worker.handle(request)["records"], first)

    def test_cache_key_preserves_smiles_case_and_trimmed_input(self):
        self.assertEqual(resolve_cache.cache_path(self.directory, "smiles", " CCO "),
                         resolve_cache.cache_path(self.directory, "smiles", "CCO"))
        self.assertNotEqual(resolve_cache.cache_path(self.directory, "smiles", "CO"),
                            resolve_cache.cache_path(self.directory, "smiles", "co"))
        self.assertNotEqual(resolve_cache.cache_path(self.directory, "auto", "CCO"),
                            resolve_cache.cache_path(self.directory, "smiles", "CCO"))

    def test_corrupt_expired_tampered_or_missing_image_falls_back(self):
        scenarios = ("invalid_json", "expired", "tampered", "missing_thumbnail")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                self.request()
                path = resolve_cache.cache_path(self.directory, "smiles", "CCO")
                if scenario == "invalid_json":
                    path.write_text("{", encoding="utf-8")
                else:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if scenario == "expired":
                        payload["created"] = time.time() - resolve_cache.TTL_SECONDS - 1
                    elif scenario == "tampered":
                        payload["records"][0]["atoms"][0]["element"] = "N"
                    else:
                        Path(payload["records"][0]["thumbnail"]).unlink()
                    path.write_text(json.dumps(payload), encoding="utf-8")
                with patch.object(worker, "_resolve", wraps=worker._resolve) as resolve:
                    self.assertTrue(self.request())
                    resolve.assert_called_once()

    def test_failed_or_empty_results_are_not_cached(self):
        with patch.object(worker, "_resolve", side_effect=worker.ChemistryError("failed")):
            with self.assertRaises(worker.ChemistryError):
                self.request(kind="name", text="unknown")
        self.assertFalse(resolve_cache.cache_path(self.directory, "name", "unknown").exists())
        with patch.object(worker, "_resolve", return_value=[]):
            self.request(kind="name", text="unknown")
        self.assertFalse(resolve_cache.cache_path(self.directory, "name", "unknown").exists())

    def test_entry_limit_and_pruning_touch_only_own_files(self):
        record = self.request()[0]
        other = self.directory / "keep.json"
        other.write_text("keep", encoding="utf-8")
        with patch.object(resolve_cache, "MAX_ENTRY_BYTES", 100):
            resolve_cache.save(self.directory, "smiles", "CCN", [record])
        self.assertFalse(resolve_cache.cache_path(self.directory, "smiles", "CCN").exists())
        with patch.object(resolve_cache, "MAX_FILES", 1):
            self.request(text="CCC")
        self.assertLessEqual(len(list(self.directory.glob(resolve_cache.PREFIX + "*.json"))), 1)
        self.assertEqual(other.read_text(encoding="utf-8"), "keep")

    def test_wrong_request_source_is_rejected(self):
        self.request()
        path = resolve_cache.cache_path(self.directory, "smiles", "CCO")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["records"][0]["source"]["input"] = "CCN"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.object(worker, "_resolve", wraps=worker._resolve) as resolve:
            self.request()
            resolve.assert_called_once()

    def test_sdf_labels_save_property_request_and_preserve_cid_order(self):
        from rdkit import Chem

        blocks = []
        for cid, smiles, label in ((2244, "CC(=O)Oc1ccccc1C(=O)O", "aspirin label"),
                                   (702, "CCO", "ethanol label")):
            mol = Chem.MolFromSmiles(smiles)
            mol.SetProp("_Name", str(cid))
            mol.SetProp("PUBCHEM_IUPAC_NAME", label)
            blocks.append(Chem.MolToMolBlock(mol) +
                          f">  <PUBCHEM_IUPAC_NAME>\n{label}\n\n$$$$\n")
        # The SDF order is deliberately different from the CID query order.
        sdf = (blocks[1] + blocks[0]).encode()
        with patch.object(worker, "_network", return_value=sdf) as network:
            records = worker._pubchem_records([2244, 702], {}, self.directory,
                                              query="test", kind="name")
        self.assertEqual([item["source"]["cid"] for item in records], [2244, 702])
        self.assertEqual([item["name"] for item in records], ["aspirin label", "ethanol label"])
        network.assert_called_once()

    def test_missing_sdf_label_uses_property_fallback(self):
        from rdkit import Chem

        mol = Chem.MolFromSmiles("CCO")
        mol.SetProp("_Name", "702")
        sdf = (Chem.MolToMolBlock(mol) + "\n$$$$\n").encode()
        names = json.dumps({"PropertyTable": {"Properties": [
            {"CID": 702, "IUPACName": "ethanol"}]}}).encode()
        with patch.object(worker, "_network", side_effect=[sdf, names]) as network:
            records = worker._pubchem_records([702], {}, self.directory,
                                              query="test", kind="name")
        self.assertEqual(records[0]["name"], "ethanol")
        self.assertEqual(network.call_count, 2)


if __name__ == "__main__":
    unittest.main()
