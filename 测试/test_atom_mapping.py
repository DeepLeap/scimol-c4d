"""Thumbnail hotspots must refer to the record's atom IDs, not canonical SMILES order."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from rdkit import Chem


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "测试" / "fixtures" / "benzyl_alcohol.cdxml"
spec = importlib.util.spec_from_file_location(
    "chemistry_worker_for_atom_mapping", ROOT / "scimol_c4d" / "chemistry_worker.py")
worker = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(worker)


class AtomMappingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name)

    def request(self, **data):
        return worker.handle({"cache_dir": str(self.cache), **data})

    def assert_hotspots_match_heavy_atoms(self, record):
        self.assertEqual(record["thumbnail_size"], [360, 280])
        expected = {str(atom["id"]) for atom in record["atoms"] if atom["element"] != "H"}
        self.assertEqual(set(record["thumbnail_atom_positions"]), expected)
        for x, y in record["thumbnail_atom_positions"].values():
            self.assertGreaterEqual(x, 0)
            self.assertLess(x, 360)
            self.assertGreaterEqual(y, 0)
            self.assertLess(y, 280)
        self.assertTrue(Path(record["thumbnail"]).is_file())
        self.assertEqual(Path(record["thumbnail"]).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue(Path(record["themed_thumbnail"]).is_file())
        with Image.open(record["thumbnail"]) as white, Image.open(record["themed_thumbnail"]) as dark:
            self.assertEqual(white.size, dark.size)
            self.assertEqual(white.size, (360, 280))
            self.assertGreater(min(white.convert("RGB").getpixel((0, 0))), 240)
            self.assertLess(max(dark.convert("RGB").getpixel((0, 0))), 80)

    def test_cdxml_oxygen_id_survives_generation(self):
        source = self.request(action="resolve", kind="file", path=str(SAMPLE))["records"][0]
        generated = self.request(action="generate", record=source)["record"]
        oxygen_id = next(atom["id"] for atom in source["atoms"] if atom["element"] == "O")
        self.assertEqual(generated["atoms"][oxygen_id]["element"], "O")
        self.assertIn(str(oxygen_id), source["thumbnail_atom_positions"])
        self.assertIn(str(oxygen_id), generated["thumbnail_atom_positions"])
        self.assert_hotspots_match_heavy_atoms(source)
        self.assert_hotspots_match_heavy_atoms(generated)

    def test_same_structure_key_with_reversed_atom_order_has_distinct_mapping(self):
        first = self.request(action="resolve", kind="smiles", text="CCO")["records"][0]
        second = self.request(action="resolve", kind="smiles", text="OCC")["records"][0]
        self.assertEqual(first["structure_key"], second["structure_key"])
        self.assertNotEqual(first["atoms"][0]["element"], second["atoms"][0]["element"])
        self.assertNotEqual(first["thumbnail"], second["thumbnail"])
        self.assertNotEqual(first["themed_thumbnail"], second["themed_thumbnail"])
        self.assertNotEqual(first["thumbnail_atom_positions"], second["thumbnail_atom_positions"])
        self.assertEqual(next(atom["id"] for atom in first["atoms"] if atom["element"] == "O"), 2)
        self.assertEqual(next(atom["id"] for atom in second["atoms"] if atom["element"] == "O"), 0)
        self.assert_hotspots_match_heavy_atoms(first)
        self.assert_hotspots_match_heavy_atoms(second)

    def test_preview_restores_hotspots_for_existing_generated_record(self):
        source = self.request(action="resolve", kind="smiles", text="CCO")["records"][0]
        generated = self.request(action="generate", record=source)["record"]
        historical = {key: value for key, value in generated.items()
                      if key not in ("thumbnail_atom_positions", "thumbnail_size",
                                     "themed_thumbnail")}
        preview = self.request(action="preview", record=historical)["record"]
        self.assert_hotspots_match_heavy_atoms(preview)
        self.assertEqual(preview["thumbnail_atom_positions"], generated["thumbnail_atom_positions"])
        self.assertEqual(preview["thumbnail"], generated["thumbnail"])
        self.assertEqual(preview["themed_thumbnail"], generated["themed_thumbnail"])

    def test_unassigned_stereo_is_not_added_to_depiction_identity(self):
        source = self.request(action="resolve", kind="smiles", text="CC(F)Cl")["records"][0]
        generated = self.request(action="generate", record=source)["record"]
        self.assertEqual(source["stereo_status"], "unspecified")
        self.assertEqual(generated["stereo_status"], "unspecified")
        self.assertEqual(generated["smiles"], source["smiles"])
        self.assertEqual(generated["thumbnail"], source["thumbnail"])
        self.assertEqual(generated["thumbnail_atom_positions"], source["thumbnail_atom_positions"])
        self.assert_hotspots_match_heavy_atoms(generated)

    def test_mismatched_graph_order_is_rejected_instead_of_guessed(self):
        record = self.request(action="resolve", kind="smiles", text="CCO")["records"][0]
        record["graph_molblock"] = Chem.MolToMolBlock(Chem.MolFromSmiles("OCC"))
        with self.assertRaisesRegex(worker.ChemistryError, "原子编号"):
            self.request(action="generate", record=record)


if __name__ == "__main__":
    unittest.main()
