"""Focused checks for the isolated RDKit worker; run with the project runtime."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "scimol_c4d" / "chemistry_worker.py"
spec = importlib.util.spec_from_file_location("chemistry_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(worker)
_LOCAL_SAMPLE = ROOT / "测试" / "fixtures" / "benzyl_alcohol.cdxml"
SAMPLE = _LOCAL_SAMPLE


class ChemistryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)

    def request(self, **data):
        return worker.handle({"cache_dir": str(self.cache), **data})

    def test_chinese_ambiguous_name_has_three_distinct_xylene_structures(self):
        records = self.request(action="resolve", kind="name", text="二甲苯")["records"]
        self.assertEqual([item["name"] for item in records], ["邻二甲苯", "间二甲苯", "对二甲苯"])
        self.assertEqual(len({item["structure_key"] for item in records}), 3)
        self.assertTrue(all(item["formula"] == "C8H10" for item in records))
        self.assertTrue(all(Path(item["thumbnail"]).is_file() for item in records))
        self.assertTrue(all(not item["has_3d"] for item in records))
        self.assertTrue(all(not item["coordinates_ready"] for item in records))
        self.assertTrue(all(any(b["aromatic"] and b["order"] == 2 for b in item["bonds"]) for item in records))

    def test_unified_input_detects_chinese_name_and_smiles_locally(self):
        for text, formula, source in (("苯环", "C6H6", "builtin_alias"),
                                      ("CCO", "C2H6O", "smiles"),
                                      ("c1ccccc1", "C6H6", "smiles")):
            records = self.request(action="resolve",kind="auto",text=text)["records"]
            self.assertEqual(records[0]["formula"],formula)
            self.assertEqual(records[0]["source"]["kind"],source)

    def test_unified_input_detects_formula_and_english_name_before_network(self):
        for text, kind in (("H2O","formula"),("ibuprofen","name")):
            with patch.object(worker,"_pubchem_cids",return_value=[1]) as query, \
                 patch.object(worker,"_pubchem_names",return_value={1:"fixture"}), \
                 patch.object(worker,"_pubchem_records",return_value=[]):
                self.request(action="resolve",kind="auto",text=text)
                query.assert_called_once_with(kind,text)

    def test_sample_cdxml_preserves_graph_and_generates_3d(self):
        self.assertTrue(SAMPLE.is_file())
        records = self.request(action="resolve", kind="file", path=str(SAMPLE))["records"]
        self.assertEqual(len(records), 1)
        source = records[0]
        self.assertEqual(source["formula"], "C7H8O")
        self.assertEqual(len(source["atoms"]), 8)
        self.assertEqual(len(source["bonds"]), 8)
        self.assertFalse(source["has_3d"])
        self.assertFalse(source["coordinates_ready"])
        generated = self.request(action="generate", record=source)["record"]
        self.assertEqual(generated["structure_key"], source["structure_key"])
        self.assertTrue(generated["has_3d"])
        self.assertTrue(generated["coordinates_ready"])
        self.assertEqual(len(generated["atoms"]), 16)
        self.assertEqual(len(generated["bonds"]), 16)
        self.assertEqual(generated["formula"], "C7H8O")

    def test_3d_file_coordinates_are_retained_when_hydrogens_are_added(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
        self.assertEqual(AllChem.EmbedMolecule(mol, randomSeed=7), 0)
        no_h = Chem.RemoveHs(mol)
        path = self.cache / "ethanol.mol"
        Chem.MolToMolFile(no_h, str(path))
        record = self.request(action="resolve", kind="file", path=str(path))["records"][0]
        self.assertTrue(record["has_3d"])
        self.assertFalse(record["coordinates_ready"])
        before = [(a["x"], a["y"], a["z"]) for a in record["atoms"]]
        generated = self.request(action="generate", record=record)["record"]
        after = [(a["x"], a["y"], a["z"]) for a in generated["atoms"][:len(before)]]
        self.assertEqual(before, after)
        self.assertTrue(generated["coordinates_ready"])
        self.assertEqual(generated["structure_key"], record["structure_key"])

    def test_unknown_stereo_is_reported_not_assigned(self):
        record = self.request(action="resolve", kind="smiles", text="CC(F)Cl")["records"][0]
        self.assertEqual(record["stereo_status"], "unspecified")
        self.assertTrue(record["warnings"])
        generated = self.request(action="generate", record=record)["record"]
        self.assertEqual(generated["structure_key"], record["structure_key"])
        self.assertEqual(generated["stereo_status"], "unspecified")
        regenerated = self.request(action="generate", record=generated)["record"]
        self.assertEqual(regenerated["structure_key"], record["structure_key"])
        self.assertEqual(regenerated["stereo_status"], "unspecified")

    def test_specified_stereo_survives_generation(self):
        for smiles in ("C[C@H](F)Cl", "F/C=C/F"):
            with self.subTest(smiles=smiles):
                record = self.request(action="resolve", kind="smiles", text=smiles)["records"][0]
                self.assertEqual(record["stereo_status"], "specified")
                generated = self.request(action="generate", record=record)["record"]
                self.assertEqual(generated["structure_key"], record["structure_key"])
                self.assertEqual(generated["stereo_status"], "specified")

    def test_sdf_malformed_entry_is_not_silently_skipped(self):
        from rdkit import Chem

        path = self.cache / "mixed.sdf"
        path.write_text(Chem.MolToMolBlock(Chem.MolFromSmiles("CCO")) + "\n$$$$\nBAD\n$$$$\n", encoding="utf-8")
        with self.assertRaisesRegex(worker.ChemistryError, "未跳过"):
            self.request(action="resolve", kind="file", path=str(path))

    def test_pubchem_formula_is_capped_and_source_is_bound_to_cid(self):
        from rdkit import Chem

        blocks = []
        for cid in range(1, worker.FORMULA_SCAN_LIMIT + 1):
            mol = Chem.MolFromSmiles("C" * (cid + 1) + "O")
            mol.SetProp("_Name", str(cid))
            blocks.append(Chem.MolToMolBlock(mol) + "\n$$$$\n")
        sdf = "".join(blocks).encode()
        with patch.object(worker, "_network", side_effect=[
            json.dumps({"IdentifierList": {"CID": list(range(1, 35))}}).encode(),
            sdf,
            json.dumps({"PropertyTable": {"Properties": [{"CID": 1, "IUPACName": "ethanol"}]}}).encode(),
        ]) as network:
            records = self.request(action="resolve", kind="formula", text="C2H6O")["records"]
        self.assertEqual(len(records), worker.MAX_CANDIDATES)
        self.assertEqual(records[0]["source"]["cid"], 1)
        self.assertEqual(records[0]["name"], "ethanol")
        self.assertEqual(network.call_count, 3)
        self.assertTrue(all("不保证穷尽" in r["warnings"][0] for r in records))

    def test_cli_emits_one_json_line(self):
        request = {"action": "resolve", "kind": "smiles", "text": "O", "cache_dir": str(self.cache)}
        result = subprocess.run([str(Path(__import__("sys").executable)), str(WORKER_PATH)],
                                input=json.dumps(request), text=True, capture_output=True, check=True)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(json.loads(lines[0])["ok"])


if __name__ == "__main__":
    unittest.main()
