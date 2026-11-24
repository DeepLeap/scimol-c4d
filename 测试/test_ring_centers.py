"""Local ring center choices and rigid orientation contracts."""

import copy
import math
import unittest

from scimol_c4d.display_geometry import orient_display_positions, ring_center_options


def cycle(elements, offset=0, aromatic=False):
    count = len(elements)
    atoms = [{"id": offset + i, "element": element} for i, element in enumerate(elements)]
    bonds = [{"a": offset + i, "b": offset + (i + 1) % count, "aromatic": aromatic}
             for i in range(count)]
    return atoms, bonds


class RingCenterTests(unittest.TestCase):
    def test_benzene_precedes_heteroaromatic_without_mislabel(self):
        hetero_atoms, hetero_bonds = cycle("CCNCCN", aromatic=True)
        carbon_atoms, carbon_bonds = cycle("CCCCCC", offset=6, aromatic=True)
        record = {"atoms": hetero_atoms + carbon_atoms, "bonds": hetero_bonds + carbon_bonds}
        expected = [{"atom_ids": list(range(6, 12)), "label": "苯环1"},
                    {"atom_ids": list(range(6)), "label": "芳香六元环1"}]
        self.assertEqual(ring_center_options(record), expected)
        self.assertEqual(ring_center_options({"atoms": list(reversed(record["atoms"])),
                                              "bonds": list(reversed(record["bonds"]))}), expected)

        positions = {}
        for offset in (0, 6):
            for i in range(6):
                theta = i * math.pi / 3
                positions[offset + i] = ([math.cos(theta), math.sin(theta), 2.0]
                                         if offset == 0 else
                                         [5.0, math.cos(theta), math.sin(theta)])
        result = orient_display_positions(record, positions, "auto")
        self.assertLess(max(abs(result[i][2]) for i in range(6, 12)), 1e-8)
        self.assertGreater(max(abs(result[i][2]) for i in range(6)), 0.5)

    def test_naphthalene_has_two_local_six_membered_rings(self):
        atoms = [{"id": i, "element": "C"} for i in range(10)]
        first = [0, 1, 2, 3, 4, 5]
        second = [4, 5, 6, 7, 8, 9]
        edges = {tuple(sorted((ring[i], ring[(i + 1) % 6])))
                 for ring in (first, second) for i in range(6)}
        record = {"atoms": atoms, "bonds": [{"a": a, "b": b, "aromatic": True}
                                               for a, b in sorted(edges)]}
        self.assertEqual(ring_center_options(record), [
            {"atom_ids": first, "label": "苯环1"},
            {"atom_ids": sorted(second), "label": "苯环2"}])

    def test_cubane_exposes_all_six_faces(self):
        record = {"atoms": [{"id": i, "element": "C"} for i in range(8)],
                  "bonds": [{"a": i, "b": j} for i in range(8)
                            for j in range(i + 1, 8) if (i ^ j).bit_count() == 1]}
        expected = {tuple(i for i in range(8) if bool(i & (1 << axis)) == side)
                    for axis in range(3) for side in (False, True)}
        options = ring_center_options(record)
        self.assertEqual({tuple(option["atom_ids"]) for option in options}, expected)
        self.assertEqual([option["label"] for option in options],
                         ["四元环" + str(i) for i in range(1, 7)])
        self.assertEqual(options, ring_center_options({"atoms": list(reversed(record["atoms"])),
                                                        "bonds": list(reversed(record["bonds"]))}))

    def test_k4_exposes_all_four_triangles(self):
        record = {"atoms": [{"id": i, "element": "C"} for i in range(4)],
                  "bonds": [{"a": i, "b": j} for i in range(4) for j in range(i + 1, 4)]}
        options = ring_center_options(record)
        self.assertEqual([option["atom_ids"] for option in options],
                         [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])

    def test_nonplanar_ring_centroid_and_all_distances_are_preserved(self):
        atoms, bonds = cycle("CCCCCC")
        record = {"atoms": atoms, "bonds": bonds}
        positions = {i: [3 + math.cos(i * math.pi / 3),
                         -2 + math.sin(i * math.pi / 3),
                         4 + (0.25 if i % 2 else -0.25)] for i in range(6)}
        before = copy.deepcopy(positions)
        self.assertEqual(ring_center_options(record),
                         [{"atom_ids": list(range(6)), "label": "六元环1"}])
        result = orient_display_positions(record, positions, "xy", list(range(6)))
        self.assertEqual(positions, before)
        for axis in range(3):
            self.assertAlmostEqual(sum(result[i][axis] for i in range(6)), 0.0, places=8)
        self.assertGreater(max(abs(result[i][2]) for i in range(6)), 0.1)
        for a in positions:
            for b in positions:
                self.assertAlmostEqual(math.dist(positions[a], positions[b]),
                                       math.dist(result[a], result[b]), places=8)

    def test_second_ring_can_be_selected_independently(self):
        a1, b1 = cycle("CCCCCC", aromatic=True)
        a2, b2 = cycle("CCCCCC", offset=6, aromatic=True)
        record = {"atoms": a1 + a2, "bonds": b1 + b2 + [{"a": 0, "b": 6}]}
        positions = {}
        for i in range(6):
            theta = i * math.pi / 3
            positions[i] = [math.cos(theta), math.sin(theta), 0.0]
            positions[i + 6] = [5.0, math.cos(theta), math.sin(theta)]
        options = ring_center_options(record)
        self.assertEqual([item["atom_ids"] for item in options],
                         [list(range(6)), list(range(6, 12))])
        result = orient_display_positions(record, positions, "xy", options[1]["atom_ids"])
        for axis in range(3):
            self.assertAlmostEqual(sum(result[i][axis] for i in range(6, 12)), 0.0, places=8)
        self.assertGreater(max(abs(result[i][2]) for i in range(6)), 0.5)

    def test_scrambled_ring_ids_align_an_actual_bond(self):
        order = [0, 3, 1, 4, 2, 5]
        record = {"atoms": [{"id": i, "element": "C"} for i in range(6)],
                  "bonds": [{"a": order[i], "b": order[(i + 1) % 6],
                             "aromatic": True} for i in range(6)]}
        positions = {}
        for index, atom_id in enumerate(order):
            theta = index * math.pi / 3
            positions[atom_id] = [2 + math.cos(theta), 3 + math.sin(theta),
                                  4 + 0.5 * math.sin(theta)]
        self.assertEqual(ring_center_options(record)[0]["atom_ids"], list(range(6)))
        self.assertNotIn({0, 1}, [{bond["a"], bond["b"]} for bond in record["bonds"]])
        result = orient_display_positions(record, positions, "auto")
        edge = [result[3][axis] - result[0][axis] for axis in range(3)]
        self.assertGreater(edge[0], 0)
        self.assertAlmostEqual(edge[1], 0.0, places=8)
        self.assertAlmostEqual(edge[2], 0.0, places=8)
        for a in positions:
            for b in positions:
                self.assertAlmostEqual(math.dist(positions[a], positions[b]),
                                       math.dist(result[a], result[b]), places=8)

    def test_empty_acyclic_and_invalid_graphs(self):
        self.assertEqual(ring_center_options({"atoms": [], "bonds": []}), [])
        self.assertEqual(ring_center_options({"atoms": [{"id": i, "element": "C"}
                                                           for i in range(3)],
                                              "bonds": [{"a": 0, "b": 1}, {"a": 1, "b": 2}]}), [])
        self.assertEqual(ring_center_options({"atoms": [{"id": i, "element": "C"}
                                                           for i in range(3)],
                                              "bonds": [{"a": 0, "b": 99}]}), [])
        self.assertEqual(ring_center_options({"atoms": [{"id": i, "element": "C"}
                                                           for i in range(3)],
                                              "bonds": [{"a": [0], "b": 1}]}), [])
        self.assertEqual(ring_center_options({"atoms": [{"id": i, "element": "C"}
                                                           for i in range(257)], "bonds": []}), [])
        self.assertEqual(ring_center_options({"atoms": [{"id": i, "element": "C"}
                                                           for i in range(60)],
                                              "bonds": [{"a": i, "b": j}
                                                        for i in range(60)
                                                        for j in range(i + 1, 60)]}), [])
        dense = ring_center_options({"atoms": [{"id": i, "element": "C"}
                                                for i in range(30)],
                                     "bonds": [{"a": i, "b": j}
                                               for i in range(30)
                                               for j in range(i + 1, 30)]})
        self.assertTrue(0 < len(dense) <= 128)
        self.assertEqual(ring_center_options(None), [])


if __name__ == "__main__":
    unittest.main()
