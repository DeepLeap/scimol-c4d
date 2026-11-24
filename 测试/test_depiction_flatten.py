"""2D depiction flattening contracts, without Cinema 4D or network access."""

import copy
import json
import math
import statistics
import tempfile
import unittest
from collections import deque
from pathlib import Path

from scimol_c4d import chemistry_worker, display_geometry
from scimol_c4d.hydrogen_layout import collision_score


FIXTURES = Path(__file__).resolve().parent / "fixtures"
OUTPUT = Path(__file__).resolve().parent / "输出"


def point(record, overrides, atom_id):
    atom = record["atoms"][atom_id]
    return overrides.get(str(atom_id), [atom["x"], atom["y"], atom["z"]])


def distance(a, b):
    return math.dist(a, b)


def external_components(record, selected):
    graph = {atom["id"]: set() for atom in record["atoms"] if atom["id"] not in selected}
    for bond in record["bonds"]:
        a, b = bond["a"], bond["b"]
        if a in graph and b in graph:
            graph[a].add(b)
            graph[b].add(a)
    components = []
    while graph:
        start = min(graph)
        seen = {start}
        queue = deque([start])
        while queue:
            for neighbor in graph[queue.popleft()] - seen:
                seen.add(neighbor)
                queue.append(neighbor)
        components.append(sorted(seen))
        for atom_id in seen:
            graph.pop(atom_id)
    return [component for component in components
            if any(record["atoms"][atom_id]["element"] != "H" for atom_id in component)]


class DepictionFlattenTests(unittest.TestCase):
    @staticmethod
    def fixture(name):
        path = FIXTURES / name
        if not path.is_file():
            path = OUTPUT / name
        return json.loads(path.read_text(encoding="utf-8"))

    def assert_depiction_layout(self, record, result):
        heavy = [atom["id"] for atom in record["atoms"] if atom["element"] != "H"]
        self.assertEqual(set(record["thumbnail_atom_positions"]), {str(i) for i in heavy})
        ratios = []
        for offset, a in enumerate(heavy):
            for b in heavy[offset+1:]:
                image = distance(record["thumbnail_atom_positions"][str(a)],
                                 record["thumbnail_atom_positions"][str(b)])
                if image > 2.0:
                    ratios.append(distance(point(record, result, a),
                                           point(record, result, b)) / image)
        scale = statistics.median(ratios)
        self.assertGreater(scale, 0)
        for ratio in ratios:
            self.assertLess(abs(ratio / scale - 1), .03)
        for offset, a in enumerate(heavy):
            for b in heavy[offset+1:]:
                self.assertGreater(distance(point(record, result, a),
                                            point(record, result, b)), .05,
                                   (a, b))

    def assert_rigid_periphery(self, record, result, selected):
        components = external_components(record, selected)
        self.assertGreaterEqual(len(components), 2)
        for component in components:
            for offset, a in enumerate(component):
                for b in component[offset+1:]:
                    self.assertAlmostEqual(distance(point(record, {}, a), point(record, {}, b)),
                                           distance(point(record, result, a), point(record, result, b)),
                                           delta=1e-5, msg=(a, b))
        for bond in record["bonds"]:
            a, b = bond["a"], bond["b"]
            if (a in selected) != (b in selected):
                self.assertAlmostEqual(distance(point(record, {}, a), point(record, {}, b)),
                                       distance(point(record, result, a), point(record, result, b)),
                                       delta=1e-5, msg=(a, b))
        return components

    def test_cholesterol_all_heavy_atoms_follow_2d_and_oh_hydrogen_is_planar(self):
        record = self.fixture("当前拍平案例.json")
        original = copy.deepcopy(record)
        result = display_geometry.flatten_overrides(record, plane="xy")
        heavy = [atom["id"] for atom in record["atoms"] if atom["element"] != "H"]
        z = [point(record, result, atom_id)[2] for atom_id in heavy]
        self.assertLess(max(z)-min(z), 1e-6)
        self.assert_depiction_layout(record, result)
        oxygen = next(atom["id"] for atom in record["atoms"] if atom["element"] == "O")
        hydroxyl_h = next(bond["b"] if bond["a"] == oxygen else bond["a"]
                          for bond in record["bonds"] if oxygen in (bond["a"], bond["b"])
                          and record["atoms"][bond["b"] if bond["a"] == oxygen
                                              else bond["a"]]["element"] == "H")
        self.assertAlmostEqual(point(record, result, hydroxyl_h)[2], z[0], delta=1e-6)
        self.assertAlmostEqual(distance(point(record, result, oxygen),
                                        point(record, result, hydroxyl_h)),
                               distance(point(record, {}, oxygen),
                                        point(record, {}, hydroxyl_h)), delta=1e-5)
        carbon_h = next(atom["id"] for atom in record["atoms"] if atom["element"] == "C"
                        and sum(1 for bond in record["bonds"] if atom["id"] in (bond["a"], bond["b"])
                                and record["atoms"][bond["b"] if bond["a"] == atom["id"]
                                                    else bond["a"]]["element"] == "H") >= 2)
        attached_h = [bond["b"] if bond["a"] == carbon_h else bond["a"]
                      for bond in record["bonds"] if carbon_h in (bond["a"], bond["b"])
                      and record["atoms"][bond["b"] if bond["a"] == carbon_h
                                          else bond["a"]]["element"] == "H"]
        for hydrogen in attached_h:
            self.assertAlmostEqual(distance(point(record, result, carbon_h),
                                            point(record, result, hydrogen)),
                                   distance(point(record, {}, carbon_h),
                                            point(record, {}, hydrogen)), delta=1e-5)
        self.assertGreater(distance(point(record, result, attached_h[0]),
                                    point(record, result, attached_h[1])), 1.)
        self.assertEqual(record, original)
        self.assertEqual(record["stereo_status"], "specified")

    def test_long_chain_middle_moves_both_rigid_outsides(self):
        record = self.fixture("二维拍平长链.json")
        selected = {4, 5, 6}
        original = copy.deepcopy(record)
        result = display_geometry.flatten_overrides(record, atom_ids=sorted(selected), plane="xy")
        components = self.assert_rigid_periphery(record, result, selected)
        left = next(component for component in components if 0 in component)
        right = next(component for component in components if 9 in component)
        self.assertGreater(distance(point(record, result, 0), point(record, {}, 0)), .01)
        self.assertGreater(distance(point(record, result, 9), point(record, {}, 9)), .01)
        self.assertLess(max(point(record, result, i)[2] for i in selected) -
                        min(point(record, result, i)[2] for i in selected), 1e-6)
        self.assertTrue(left and right)
        self.assertEqual(record, original)

    def test_branch_peripheries_remain_rigid_and_follow_selected_core(self):
        record = self.fixture("二维拍平分叉.json")
        selected = {1, 3, 4}
        result = display_geometry.flatten_overrides(record, atom_ids=sorted(selected), plane="xy")
        components = self.assert_rigid_periphery(record, result, selected)
        self.assertGreaterEqual(len(components), 4)
        for heavy_id in (0, 2, 5, 6):
            self.assertTrue(any(heavy_id in part for part in components))
            self.assertGreater(distance(point(record, result, heavy_id),
                                        point(record, {}, heavy_id)), .01)

    def test_outer_branch_torsion_reduces_collision_without_stretching(self):
        positions = {0: [0., 0., 0.], 1: [1.5, 0., 0.],
                     2: [3., 1., 0.], 3: [3., 1., 0.]}
        original = copy.deepcopy(positions)
        elements = {i: "C" for i in positions}
        bonds = [{"a": 0, "b": 1, "order": 1},
                 {"a": 1, "b": 2, "order": 1}]
        frames = {0: {"members": {1, 2}, "origin": positions[1][:],
                      "normal": [0., 0., 1.]}}
        moved = display_geometry._spread_outer_branches(
            positions, [(0, 1, {1, 2})], [0., 0., 1.], elements, bonds, frames)
        self.assertLess(collision_score(moved, elements, bonds),
                        collision_score(positions, elements, bonds))
        self.assertEqual(moved[0], original[0])
        self.assertEqual(moved[1], original[1])
        self.assertEqual(moved[3], original[3])
        self.assertAlmostEqual(math.dist(moved[1], moved[2]),
                               math.dist(original[1], original[2]), delta=1e-8)
        for atom_id in (1, 2):
            relative = display_geometry._sub(moved[atom_id], frames[0]["origin"])
            self.assertAlmostEqual(display_geometry._dot(relative, frames[0]["normal"]),
                                   0., delta=1e-8)
        repeat = display_geometry._spread_outer_branches(
            moved, [(0, 1, {1, 2})], [0., 0., 1.], elements, bonds, frames)
        for atom_id in moved:
            self.assertLess(math.dist(moved[atom_id], repeat[atom_id]), 1e-8)
        self.assertEqual(positions, original)

    def test_outer_multiple_bond_does_not_gain_axial_torsion(self):
        positions = {0: [0., 0., 0.], 1: [1.5, 0., 0.],
                     2: [3., 1., 0.], 3: [3., 1., 0.]}
        bonds = [{"a": 0, "b": 1, "order": 2}, {"a": 1, "b": 2, "order": 1}]
        moved = display_geometry._spread_outer_branches(
            positions, [(0, 1, {1, 2})], [0., 0., 1.],
            {i: "C" for i in positions}, bonds)
        self.assertEqual(moved, positions)

    def test_distant_clear_branch_keeps_its_original_roll(self):
        positions = {0: [0., 0., 0.], 1: [1.5, 0., 0.],
                     2: [3., 1., 0.], 3: [3., 1., 0.],
                     4: [0., 10., 0.], 5: [1.5, 10., 0.], 6: [3., 11., 0.]}
        bonds = [{"a": a, "b": b, "order": 1} for a, b in ((0, 1), (1, 2), (4, 5), (5, 6))]
        moved = display_geometry._spread_outer_branches(
            positions, [(0, 1, {1, 2}), (4, 5, {5, 6})], [0., 0., 1.],
            {i: "C" for i in positions}, bonds)
        self.assertGreater(math.dist(moved[2], positions[2]), .5)
        for atom_id in (4, 5, 6):
            self.assertEqual(moved[atom_id], positions[atom_id])
        repeat = display_geometry._spread_outer_branches(
            moved, [(0, 1, {1, 2}), (4, 5, {5, 6})], [0., 0., 1.],
            {i: "C" for i in positions}, bonds)
        for atom_id in moved:
            self.assertLess(math.dist(moved[atom_id], repeat[atom_id]), 1e-8)

    def test_repeated_flatten_and_three_axis_planes_are_finite(self):
        record = self.fixture("二维拍平长链.json")
        for plane, flat_axis in (("xy", 2), ("xz", 1), ("yz", 0)):
            with self.subTest(plane=plane):
                first = display_geometry.flatten_overrides(record, plane=plane)
                second = display_geometry.flatten_overrides(record, first, plane=plane)
                self.assertEqual(set(first), set(second))
                for atom_id in first:
                    self.assertTrue(all(math.isfinite(value) for value in first[atom_id]))
                    self.assertLess(distance(first[atom_id], second[atom_id]), 1e-6)
                heavy = [atom["id"] for atom in record["atoms"] if atom["element"] != "H"]
                values = [point(record, first, atom_id)[flat_axis] for atom_id in heavy]
                self.assertLess(max(values)-min(values), 1e-6)

    def test_repeated_local_middle_and_partial_ring_remain_bounded(self):
        chain = self.fixture("二维拍平长链.json")
        first = display_geometry.flatten_overrides(chain, atom_ids=[4, 5, 6], plane="xy")
        second = display_geometry.flatten_overrides(chain, first, atom_ids=[4, 5, 6], plane="xy")
        for atom_id in set(first) | set(second):
            self.assertLess(distance(point(chain, first, int(atom_id)),
                                     point(chain, second, int(atom_id))), 1e-6)
        cholesterol = self.fixture("当前拍平案例.json")
        ring = display_geometry.ring_center_options(cholesterol)[0]["atom_ids"]
        result = display_geometry.flatten_overrides(cholesterol, atom_ids=ring[:3], plane="xy")
        heavy = [atom["id"] for atom in cholesterol["atoms"] if atom["element"] != "H"]
        for bond in cholesterol["bonds"]:
            a, b = bond["a"], bond["b"]
            if a not in heavy or b not in heavy:
                continue
            original = distance(point(cholesterol, {}, a), point(cholesterol, {}, b))
            displayed = distance(point(cholesterol, result, a), point(cholesterol, result, b))
            self.assertGreater(displayed, .1, (a, b))
            self.assertLess(displayed / original, 2., (a, b))

    def test_smiles_atom_order_uses_each_records_own_hotspots(self):
        with tempfile.TemporaryDirectory() as directory:
            records = []
            for smiles in ("CCO", "OCC"):
                source = chemistry_worker.handle({"action": "resolve", "kind": "smiles",
                                                  "text": smiles, "cache_dir": directory})["records"][0]
                records.append(chemistry_worker.handle({"action": "generate", "record": source,
                                                        "cache_dir": directory})["record"])
        self.assertEqual(records[0]["structure_key"], records[1]["structure_key"])
        self.assertNotEqual(records[0]["thumbnail_atom_positions"],
                            records[1]["thumbnail_atom_positions"])
        for record in records:
            result = display_geometry.flatten_overrides(record, plane="xy")
            self.assert_depiction_layout(record, result)


if __name__ == "__main__":
    unittest.main()
