"""Local hydrogen placement around a fixed flattened heavy-atom skeleton."""

import copy
import json
import math
import unittest
from pathlib import Path

from scimol_c4d import hydrogen_layout as layout
from scimol_c4d.display_geometry import flatten_overrides


_FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = _FIXTURES / "当前拍平案例.json"
if not FIXTURE.is_file():
    FIXTURE = Path(__file__).resolve().parent / "输出" / "当前拍平案例.json"


def molecule(elements, bonds):
    return {"atoms": [{"id": i, "element": element} for i, element in enumerate(elements)],
            "bonds": [{"a": a, "b": b, "order": order, "aromatic": aromatic}
                      for a, b, order, aromatic in bonds]}


def bonded(a, b, order=1., aromatic=False):
    return (a, b, order, aromatic)


class HydrogenLayoutTests(unittest.TestCase):
    def assert_fixed_heavy_and_lengths(self, record, source, moved, result):
        elements = {atom["id"]: atom["element"] for atom in record["atoms"]}
        for atom_id, element in elements.items():
            if element != "H":
                self.assertEqual(result[atom_id], moved[atom_id])
        for bond in record["bonds"]:
            a, b = bond["a"], bond["b"]
            if elements[a] == "H" or elements[b] == "H":
                self.assertAlmostEqual(math.dist(result[a], result[b]),
                                       math.dist(source[a], source[b]), delta=1e-8)

    def test_opposite_heavy_neighbors_spread_ch2_on_both_sides(self):
        record = molecule(["C", "C", "C", "H", "H"],
                          [bonded(0, 1), bonded(0, 2), bonded(0, 3), bonded(0, 4)])
        source = {0: [0., 0., 0.], 1: [-1., .2, 0.], 2: [1., .2, 0.],
                  3: [0., -.6, .8], 4: [0., -.6, -.8]}
        moved = copy.deepcopy(source)
        moved[1] = [-1., 0., 0.]
        moved[2] = [1., 0., 0.]
        original_source, original_moved = copy.deepcopy(source), copy.deepcopy(moved)
        result = layout.arrange_hydrogens(record, source, moved, {0}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        self.assertLess((result[3][2] - result[0][2]) *
                        (result[4][2] - result[0][2]), 0.)
        self.assertGreater(math.dist(result[3], result[4]), 1.2)
        self.assertEqual(source, original_source)
        self.assertEqual(moved, original_moved)
        self.assertEqual(result, layout.arrange_hydrogens(
            record, source, result, {0}, [0., 0., 1.]))

    def test_ch3_forms_three_distinct_tetrahedral_cone_directions(self):
        record = molecule(["C", "C", "H", "H", "H"],
                          [bonded(0, 1), bonded(0, 2), bonded(0, 3), bonded(0, 4)])
        source = {0: [0., 0., 0.], 1: [1., 0., 0.],
                  2: [-1./3., .94, 0.],
                  3: [-1./3., -.47, .81], 4: [-1./3., -.47, -.81]}
        moved = copy.deepcopy(source)
        moved[1] = [0., 1., 0.]
        result = layout.arrange_hydrogens(record, source, moved, {0}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        axis = [moved[1][i] - moved[0][i] for i in range(3)]
        for hydrogen in (2, 3, 4):
            direction = [result[hydrogen][i] - result[0][i] for i in range(3)]
            self.assertAlmostEqual(sum(axis[i] * direction[i] for i in range(3)) /
                                   math.dist(result[hydrogen], result[0]), -1./3., delta=1e-8)
        for a, b in ((2, 3), (2, 4), (3, 4)):
            self.assertGreater(math.dist(result[a], result[b]), 1.5)

    def test_terminal_alkene_ch2_follows_new_bond_in_plane(self):
        record = molecule(["C", "C", "H", "H"],
                          [bonded(0, 1, 2.), bonded(0, 2), bonded(0, 3)])
        source = {0: [0., 0., 0.], 1: [1., 0., 0.],
                  2: [-.5, .8660254, 0.], 3: [-.5, -.8660254, 0.]}
        moved = copy.deepcopy(source)
        moved[1] = [0., 1., 0.]
        result = layout.arrange_hydrogens(record, source, moved, {0}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        self.assertAlmostEqual(result[2][2], 0., delta=1e-9)
        self.assertAlmostEqual(result[3][2], 0., delta=1e-9)
        self.assertAlmostEqual(result[2][1] / math.dist(result[0], result[2]), -.5,
                               delta=1e-9)
        self.assertAlmostEqual(result[3][1] / math.dist(result[0], result[3]), -.5,
                               delta=1e-9)

    def test_unusual_nh2_rotates_source_family_with_heavy_axis(self):
        record = molecule(["N", "C", "H", "H"],
                          [bonded(0, 1), bonded(0, 2), bonded(0, 3)])
        source = {0: [0., 0., 0.], 1: [1., 0., 0.],
                  2: [-.5, .8660254, 0.], 3: [-.5, -.8660254, 0.]}
        moved = copy.deepcopy(source)
        moved[1] = [0., 1., 0.]
        result = layout.arrange_hydrogens(record, source, moved, {0}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        self.assertAlmostEqual(result[2][0], -.8660254, delta=1e-7)
        self.assertAlmostEqual(result[2][1], -.5, delta=1e-7)
        self.assertAlmostEqual(result[3][0], .8660254, delta=1e-7)
        self.assertAlmostEqual(result[3][1], -.5, delta=1e-7)

    def test_symmetric_three_heavy_ch_uses_source_side_normal(self):
        record = molecule(["C", "C", "C", "C", "H"],
                          [bonded(0, 1), bonded(0, 2), bonded(0, 3), bonded(0, 4)])
        source = {0: [0., 0., 0.], 1: [1., 0., 0.],
                  2: [-.5, .8660254, 0.], 3: [-.5, -.8660254, 0.],
                  4: [0., 0., -1.]}
        moved = copy.deepcopy(source)
        result = layout.arrange_hydrogens(record, source, moved, {0}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        self.assertAlmostEqual(result[4][0], 0., delta=1e-9)
        self.assertAlmostEqual(result[4][1], 0., delta=1e-9)
        self.assertAlmostEqual(result[4][2], -1., delta=1e-9)

    def test_planar_aromatic_ch_and_hydroxyl_h(self):
        record = molecule(["C", "C", "C", "H", "O", "C", "H"],
                          [bonded(0, 1, 1.5, True), bonded(0, 2, 1.5, True),
                           bonded(0, 3), bonded(4, 5), bonded(4, 6)])
        source = {0: [0., 0., 0.], 1: [-1., 0., 0.], 2: [.5, .87, 0.],
                  3: [.5, -.87, 0.], 4: [3., 0., 0.], 5: [4., 0., 0.],
                  6: [2.1, 0., .4]}
        moved = copy.deepcopy(source)
        moved[2] = [.5, 1., 0.]
        moved[5] = [4., .2, 0.]
        result = layout.arrange_hydrogens(record, source, moved, {0, 4}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        self.assertAlmostEqual(result[3][2], 0., delta=1e-9)
        self.assertAlmostEqual(result[6][2], 0., delta=1e-9)

    def test_unobstructed_oh_keeps_source_angle_when_heavy_bond_turns(self):
        record = molecule(["O", "C", "H"], [bonded(0, 1), bonded(0, 2)])
        theta = math.radians(109.)
        source = {0: [0., 0., 0.], 1: [1.43, 0., 0.],
                  2: [.96 * math.cos(theta), .96 * math.sin(theta), 0.]}
        moved = copy.deepcopy(source)
        moved[1] = [0., 1.43, 0.]
        result = layout.arrange_hydrogens(record, source, moved, {0}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        self.assertAlmostEqual(result[2][2], 0., delta=1e-9)
        direction = [result[2][i] / .96 for i in range(3)]
        angle = math.degrees(math.acos(max(-1., min(1., direction[1]))))
        self.assertAlmostEqual(angle, 109., delta=1e-7)
        self.assertLess(result[2][0], 0.)

    def test_ch_with_three_heavy_neighbors_uses_original_side(self):
        record = molecule(["C", "C", "C", "C", "H"],
                          [bonded(0, 1), bonded(0, 2), bonded(0, 3), bonded(0, 4)])
        source = {0: [0., 0., 0.], 1: [1., 0., 0.], 2: [-.5, .87, 0.],
                  3: [-.5, -.87, 0.], 4: [0., 0., -1.]}
        moved = copy.deepcopy(source)
        moved[1] = [0., 1., 0.]
        result = layout.arrange_hydrogens(record, source, moved, {0}, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        self.assertLess(result[4][2], -.2)

    def test_cholesterol_has_fixed_heavy_centers_and_no_worse_soft_collisions(self):
        record = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source = {atom["id"]: [atom[axis] for axis in ("x", "y", "z")]
                  for atom in record["atoms"]}
        depiction = flatten_overrides(record, plane="xy")
        moved = {atom_id: depiction[str(atom_id)] for atom_id in source}
        before = copy.deepcopy(record), copy.deepcopy(source), copy.deepcopy(moved)
        heavy = {atom_id for atom_id in source if record["atoms"][atom_id]["element"] != "H"}
        result = layout.arrange_hydrogens(record, source, moved, heavy, [0., 0., 1.])
        self.assert_fixed_heavy_and_lengths(record, source, moved, result)
        elements = {atom["id"]: atom["element"] for atom in record["atoms"]}
        self.assertLessEqual(layout.collision_score(result, elements, record["bonds"]),
                             layout.collision_score(moved, elements, record["bonds"]) + 1e-7)
        self.assertEqual((record, source, moved), before)
        repeated = layout.arrange_hydrogens(record, source, result, heavy, [0., 0., 1.])
        for atom_id in result:
            self.assertLess(math.dist(result[atom_id], repeated[atom_id]), 1e-9)
        graph = {atom_id: [] for atom_id in source}
        for bond in record["bonds"]:
            a, b = bond["a"], bond["b"]
            graph[a].append(b)
            graph[b].append(a)

        def handed_volume(positions, neighbors, hydrogen):
            first, second, third = neighbors
            a = [positions[first][i] - positions[third][i] for i in range(3)]
            b = [positions[second][i] - positions[third][i] for i in range(3)]
            h = [positions[hydrogen][i] - positions[third][i] for i in range(3)]
            return ((a[1]*b[2]-a[2]*b[1])*h[0] +
                    (a[2]*b[0]-a[0]*b[2])*h[1] +
                    (a[0]*b[1]-a[1]*b[0])*h[2])

        checked_chirality = 0
        for atom_id in sorted(heavy):
            if elements[atom_id] != "C":
                continue
            neighbors = sorted(item for item in graph[atom_id] if elements[item] != "H")
            hydrogens = [item for item in graph[atom_id] if elements[item] == "H"]
            if len(neighbors) != 3 or len(hydrogens) != 1:
                continue
            source_volume = handed_volume(source, neighbors, hydrogens[0])
            result_volume = handed_volume(result, neighbors, hydrogens[0])
            if abs(source_volume) > 1e-8 and abs(result_volume) > 1e-8:
                self.assertGreater(source_volume * result_volume, 0.,
                                   msg=f"C{atom_id} inverted after flattening")
                checked_chirality += 1
        self.assertEqual(checked_chirality, 7)

    def test_collision_score_and_axis_rotation_have_bounded_geometry_semantics(self):
        positions = {0: [0., 0., 0.], 1: [1., 0., 0.], 2: [1.2, 0., 0.]}
        elements = {0: "C", 1: "H", 2: "H"}
        bonds = [bonded(0, 1)]
        self.assertGreater(layout.collision_score(positions, elements, bonds), 0.)
        self.assertEqual(layout.collision_score(positions, elements, bonds, [(0, 1)]), 0.)
        rotated = layout.rotate_about_axis([1., 0., 0.], [0., 0., 1.], math.pi/2.)
        self.assertAlmostEqual(rotated[0], 0., delta=1e-10)
        self.assertAlmostEqual(rotated[1], 1., delta=1e-10)
        self.assertAlmostEqual(math.dist(rotated, [0., 0., 0.]), 1., delta=1e-10)


if __name__ == "__main__":
    unittest.main()
