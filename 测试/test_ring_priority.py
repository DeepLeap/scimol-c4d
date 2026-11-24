"""Regression checks for automatic ring center priority."""

import json
import math
import unittest
from pathlib import Path

from scimol_c4d.display_geometry import orient_display_positions, ring_center_options


class RingPriorityTests(unittest.TestCase):
    def test_caffeine_auto_centers_six_membered_ring(self):
        fixture_path = Path(__file__).parent / "fixtures" / "常用结构.json"
        if not fixture_path.is_file():
            fixture_path = Path(__file__).parent / "输出" / "常用结构.json"
        fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
        record = next(item for item in fixtures if item["name"] == "咖啡因")
        # The saved chemical graph has placeholder coordinates; its molblock
        # supplies the corresponding generated 2D geometry for this test.
        lines = record["molblock"].splitlines()
        raw = {atom["id"]: [float(value) for value in
               (lines[4 + atom["id"]][0:10], lines[4 + atom["id"]][10:20],
                lines[4 + atom["id"]][20:30])]
               for atom in record["atoms"]}
        # Tilt the real molecular geometry out of XY so auto must rotate it.
        positions = {atom_id: [x, y * math.sqrt(3) / 2, y / 2]
                     for atom_id, (x, y, _z) in raw.items()}
        six = [1, 2, 4, 5, 10, 12]
        five = [4, 5, 6, 7, 8]
        options = ring_center_options(record)
        self.assertEqual(options[0]["atom_ids"], six)
        self.assertNotIn("苯环", options[0]["label"])
        self.assertEqual(options[1]["atom_ids"], five)

        auto = orient_display_positions(record, positions, "auto")
        selected = orient_display_positions(record, positions, "auto", six)
        for axis in range(3):
            self.assertAlmostEqual(sum(auto[i][axis] for i in six) / 6, 0, places=8)
            self.assertAlmostEqual(auto[six[0]][axis], selected[six[0]][axis], places=8)
        self.assertGreater(math.dist([sum(auto[i][axis] for i in five) / 5
                                      for axis in range(3)], [0, 0, 0]), 0.1)
        for a in positions:
            for b in positions:
                self.assertAlmostEqual(math.dist(positions[a], positions[b]),
                                       math.dist(auto[a], auto[b]), places=8)

        manual_five = orient_display_positions(record, positions, "auto", five)
        for axis in range(3):
            self.assertAlmostEqual(sum(manual_five[i][axis] for i in five) / 5,
                                   0, places=8)

    def test_benzene_precedes_five_membered_ring(self):
        atoms = [{"id": i, "element": "C"} for i in range(11)]
        bonds = ([{"a": i, "b": (i + 1) % 6, "aromatic": True}
                  for i in range(6)] +
                 [{"a": 6 + i, "b": 6 + (i + 1) % 5, "aromatic": True}
                  for i in range(5)] + [{"a": 0, "b": 6}])
        record = {"atoms": atoms, "bonds": bonds}
        positions = {}
        for count, offset, x in ((6, 0, 0.0), (5, 6, 5.0)):
            for i in range(count):
                angle = 2 * math.pi * i / count
                positions[offset + i] = [x + math.cos(angle), math.sin(angle), 0.0]
        self.assertEqual(ring_center_options(record)[0]["atom_ids"], list(range(6)))
        auto = orient_display_positions(record, positions, "auto")
        self.assertAlmostEqual(sum(auto[i][0] for i in range(6)) / 6, 0, places=8)
        explicit = orient_display_positions(record, positions, "auto", list(range(6, 11)))
        self.assertAlmostEqual(sum(explicit[i][0] for i in range(6, 11)) / 5,
                               0, places=8)

    def test_auto_uses_planar_five_when_six_is_puckered(self):
        atoms = [{"id": i, "element": "C"} for i in range(11)]
        bonds = ([{"a": i, "b": (i + 1) % 6, "aromatic": True}
                  for i in range(6)] +
                 [{"a": 6 + i, "b": 6 + (i + 1) % 5, "aromatic": True}
                  for i in range(5)])
        record = {"atoms": atoms, "bonds": bonds}
        positions = {}
        for i in range(6):
            angle = 2 * math.pi * i / 6
            positions[i] = [math.cos(angle), math.sin(angle),
                            0.4 if i % 2 else -0.4]
        for i in range(5):
            angle = 2 * math.pi * i / 5
            positions[6 + i] = [4 + math.cos(angle), math.sin(angle), 0.0]
        result = orient_display_positions(record, positions, "auto")
        for axis in range(3):
            self.assertAlmostEqual(sum(result[i][axis] for i in range(6, 11)) / 5,
                                   0, places=8)


if __name__ == "__main__":
    unittest.main()
