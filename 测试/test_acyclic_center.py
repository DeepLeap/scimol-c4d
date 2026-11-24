"""Acyclic display center and bond-axis orientation contracts."""

import math
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scimol_c4d.display_geometry import orient_display_positions


class AcyclicCenterTests(unittest.TestCase):
    def assert_rigid(self, before, after):
        for first in before:
            for second in before:
                self.assertAlmostEqual(math.dist(before[first], before[second]),
                                       math.dist(after[first], after[second]), places=8)

    def test_ethanol_auto_uses_middle_carbon_and_terminal_carbon_axis(self):
        record = {"atoms": [{"id": i, "element": element}
                            for i, element in enumerate(("C", "C", "O", "H", "H", "H"))],
                  "bonds": [{"a": a, "b": b} for a, b in
                            ((0, 1), (1, 2), (0, 3), (1, 4), (2, 5))]}
        positions = {0: [2., 3., 4.], 1: [3., 4., 5.], 2: [4., 4., 4.5],
                     3: [1.4, 2.7, 4.8], 4: [3.2, 4.2, 6.], 5: [4.7, 4.6, 4.6]}
        for preset in ("auto", "xy", "xz"):
            with self.subTest(preset=preset):
                result = orient_display_positions(record, positions, preset)
                self.assertEqual(result[1], [0.0, 0.0, 0.0])
                self.assertGreater(result[0][0], 0)
                self.assertAlmostEqual(result[0][1], 0.0, places=8)
                self.assertAlmostEqual(result[0][2], 0.0, places=8)
                self.assertGreater(result[2][1 if preset != "xz" else 2], 0)
                self.assert_rigid(positions, result)

    def test_acetate_graph_center_is_carbon_not_terminal_oxygen(self):
        record = {"atoms": [{"id": i, "element": element}
                            for i, element in enumerate(("C", "C", "O", "O", "H"))],
                  "bonds": [{"a": a, "b": b} for a, b in
                            ((0, 1), (1, 2), (1, 3), (0, 4))]}
        positions = {0: [1., 2., 3.], 1: [2., 3., 4.], 2: [2., 4., 4.],
                     3: [3., 2.8, 3.8], 4: [.5, 1.3, 3.5]}
        result = orient_display_positions(record, positions, "auto")
        self.assertEqual(result[1], [0.0, 0.0, 0.0])
        self.assertGreater(result[0][0], 0)
        self.assertAlmostEqual(result[0][1], 0.0, places=8)
        self.assertAlmostEqual(result[0][2], 0.0, places=8)
        self.assertGreater(result[2][1], 0)
        self.assert_rigid(positions, result)

    def test_explicit_single_center_and_original_preserve_intent(self):
        record = {"atoms": [{"id": i, "element": "C"} for i in range(3)],
                  "bonds": [{"a": 0, "b": 1}, {"a": 1, "b": 2}]}
        positions = {0: [2., 3., 4.], 1: [3., 4., 5.], 2: [4., 4., 4.]}
        result = orient_display_positions(record, positions, "auto", [0])
        self.assertEqual(result[0], [0.0, 0.0, 0.0])
        self.assertGreater(result[1][0], 0)
        self.assertAlmostEqual(result[1][1], 0.0, places=8)
        self.assertAlmostEqual(result[1][2], 0.0, places=8)
        original = orient_display_positions(record, positions, "original", [0])
        self.assertEqual(original[1], [1.0, 1.0, 1.0])
        self.assert_rigid(positions, result)

    def test_symmetric_chain_tie_uses_stable_id_and_longer_branch(self):
        record = {"atoms": [{"id": i, "element": "C"} for i in range(4)],
                  "bonds": [{"a": i, "b": i + 1} for i in range(3)]}
        positions = {0: [-3., -1., 0.], 1: [-1., 0., 0.],
                     2: [1., 1., 0.], 3: [3., 2., 0.]}
        result = orient_display_positions(record, positions, "auto")
        self.assertEqual(result[1], [0.0, 0.0, 0.0])
        self.assertGreater(result[2][0], 0)
        self.assertAlmostEqual(result[2][1], 0.0, places=8)
        shuffled = {"atoms": list(reversed(record["atoms"])),
                    "bonds": list(reversed(record["bonds"]))}
        self.assertEqual(result, orient_display_positions(shuffled, positions, "auto"))

    def test_benzene_still_precedes_acyclic_graph_center(self):
        atoms = [{"id": i, "element": "C"} for i in range(9)]
        bonds = [{"a": 0, "b": 1}, {"a": 1, "b": 2}]
        positions = {0: [0., 0., 0.], 1: [1., 1., 0.], 2: [2., 1., 0.]}
        for i in range(6):
            theta = i * math.pi / 3
            positions[i + 3] = [10 + math.cos(theta), math.sin(theta),
                                1 + .5 * math.sin(theta)]
            bonds.append({"a": i + 3, "b": (i + 1) % 6 + 3, "aromatic": True})
        result = orient_display_positions({"atoms": atoms, "bonds": bonds},
                                          positions, "auto")
        for axis in range(3):
            self.assertAlmostEqual(sum(result[i][axis] for i in range(3, 9)),
                                   0.0, places=8)
        self.assert_rigid(positions, result)


if __name__ == "__main__":
    unittest.main()
