"""Behavior checks for the pure-Python display flattening operation."""

import copy
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scimol_c4d import display_geometry
from scimol_c4d.display_geometry import apply_plane_groups, flatten_overrides, make_plane_group


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("chemistry_worker", ROOT / "scimol_c4d" / "chemistry_worker.py")
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def position(record, atom_id):
    atom = record["atoms"][atom_id]
    return [atom[axis] for axis in ("x", "y", "z")]


def distance(a, b):
    return math.dist(a, b)


def assert_bonds_preserved(case, record, overrides):
    for bond in record["bonds"]:
        a, b = bond["a"], bond["b"]
        before = distance(position(record, a), position(record, b))
        after = distance(overrides.get(str(a), position(record, a)),
                         overrides.get(str(b), position(record, b)))
        case.assertLess(abs(after-before), 1e-6, (a, b))


class DisplayGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = WORKER.handle({"action": "resolve", "kind": "smiles", "text": "OCc1ccccc1",
                                "cache_dir": cls.temp.name})["records"][0]
        cls.record = WORKER.handle({"action": "generate", "record": source,
                                    "cache_dir": cls.temp.name})["record"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_cholesterol_preview_flattens_nonplanar_fused_rings(self):
        record = json.loads((ROOT / "测试" / "输出" / "当前拍平案例.json")
                            .read_text(encoding="utf-8"))
        before = copy.deepcopy(record)
        heavy = [atom["id"] for atom in record["atoms"] if atom["element"] != "H"]
        result = flatten_overrides(record, plane="xy")
        self.assertEqual(set(result), {str(atom["id"]) for atom in record["atoms"]})
        self.assertLess(max(abs(result[str(i)][2] - result[str(heavy[0])][2])
                            for i in heavy), 1e-7)
        self.assertGreater(distance(result["1"], position(record, 1)), .1)
        self.assertEqual(record, before)

    def test_cholesterol_middle_chain_moves_both_outer_components_rigidly(self):
        record = json.loads((ROOT / "测试" / "输出" / "当前拍平案例.json")
                            .read_text(encoding="utf-8"))
        result = flatten_overrides(record, atom_ids=[23, 24], plane="xy")
        self.assertGreater(distance(result["20"], position(record, 20)), 1e-4)
        self.assertGreater(distance(result["25"], position(record, 25)), 1e-4)
        for a, b in ((20, 23), (24, 25), (20, 12), (25, 26), (25, 27)):
            self.assertAlmostEqual(distance(result[str(a)], result[str(b)]),
                                   distance(position(record, a), position(record, b)), places=7)
        repeat = flatten_overrides(record, result, atom_ids=[23, 24], plane="xy")
        for atom_id in result:
            self.assertLess(distance(result[atom_id], repeat[atom_id]), 1e-7)

    def test_cholesterol_plane_groups_flatten_ring_and_reject_real_conflict(self):
        record = json.loads((ROOT / "测试" / "输出" / "当前拍平案例.json")
                            .read_text(encoding="utf-8"))
        first = {"atom_ids": [1, 2], "origin": [0, 0, 0],
                 "normal": [0, 0, 1]}
        result = apply_plane_groups(record, {"1": first})
        for atom_id in (1, 2):
            self.assertAlmostEqual(result[str(atom_id)][2], 0, places=8)
        self.assertEqual(set(result), {str(atom["id"]) for atom in record["atoms"]})
        different = {"atom_ids": [3], "origin": [0, 0, 0],
                     "normal": [0, 1, 0]}
        with self.assertRaisesRegex(ValueError, "目标平面冲突"):
            apply_plane_groups(record, {"1": first, "2": different})

    def test_two_separate_chain_groups_keep_distinct_planes_and_repeat(self):
        record = json.loads((ROOT / "测试" / "输出" / "二维拍平长链.json")
                            .read_text(encoding="utf-8"))
        original = copy.deepcopy(record)
        groups = {
            "2": {"atom_ids": [6, 7, 8, 9], "origin": [0, 0, 0],
                  "normal": [0, 1, 0]},
            "1": {"atom_ids": [0, 1, 2, 3], "origin": [0, 0, 0],
                  "normal": [0, 0, 1]},
        }
        saved_groups = copy.deepcopy(groups)
        first = apply_plane_groups(record, groups)
        for ids in ([0, 1, 2, 3], [6, 7, 8, 9]):
            origin, normal = display_geometry._plane([first[str(i)] for i in ids])
            self.assertLess(max(abs(sum((first[str(i)][axis]-origin[axis])*normal[axis]
                                        for axis in range(3))) for i in ids), 1e-7)
        for a, b in ((3, 4), (5, 6)):
            self.assertAlmostEqual(distance(first[str(a)], first[str(b)]),
                                   distance(position(record, a), position(record, b)), places=7)
        second = apply_plane_groups(record, groups, first)
        for atom_id in first:
            self.assertLess(distance(first[atom_id], second[atom_id]), 1e-6)
        translated = {str(atom["id"]): [atom[axis] + offset
                                        for axis, offset in zip(("x", "y", "z"), (1., 2., 3.))]
                      for atom in record["atoms"]}
        shifted_first = apply_plane_groups(record, groups, translated)
        self.assertGreater(max(distance(shifted_first[key], first[key]) for key in first), .1)
        shifted_second = apply_plane_groups(record, groups, shifted_first)
        self.assertLess(max(distance(shifted_first[key], shifted_second[key])
                            for key in shifted_first), 1e-6)
        self.assertEqual(record, original)
        self.assertEqual(groups, saved_groups)

    def test_carried_group_plane_uses_the_same_rigid_transform_as_its_atoms(self):
        record = json.loads((ROOT / "测试" / "输出" / "二维拍平长链.json")
                            .read_text(encoding="utf-8"))
        by_id, positions, heavy = display_geometry._record_positions(record)
        depiction = display_geometry._depiction_points(record, positions, heavy)
        carried = {}
        first = display_geometry._depiction_flatten(
            record, positions, heavy, {0, 1, 2, 3}, {}, depiction,
            group_plane=([0, 0, 0], [0, 0, 1]), carried_planes=carried)
        carried["1"] = {"members": {0, 1, 2, 3},
                        "origin": [0., 0., 0.], "normal": [0., 0., 1.]}
        second = display_geometry._depiction_flatten(
            record, positions, heavy, {6, 7, 8, 9}, first, depiction,
            group_plane=([0, 0, 0], [0, 1, 0]), carried_planes=carried)
        effective = carried["1"]
        self.assertGreater(abs(effective["origin"][2]), .01)
        self.assertLess(abs(effective["normal"][2]), .99)
        self.assertLess(max(abs(sum((second[str(i)][axis]-effective["origin"][axis])*
                                    effective["normal"][axis] for axis in range(3)))
                            for i in effective["members"]), 1e-7)

    def test_different_planes_reject_intersection_only_in_closed_paths(self):
        # Both requested leaf pairs are disjoint; closure adds only center 0
        # to each group, so the conflict exists solely at an implicit member.
        xyz = ((0., 0., .2), (-1., 0., 0.), (1., 0., .1),
               (0., 1., -.1), (0., -1., 0.))
        record = {
            "atoms": [{"id": atom_id, "element": "C", "x": x, "y": y, "z": z}
                      for atom_id, (x, y, z) in enumerate(xyz)],
            "bonds": [{"a": 0, "b": leaf, "order": 1} for leaf in range(1, 5)],
            "thumbnail_atom_positions": {
                str(atom_id): [x * 100., y * 100.]
                for atom_id, (x, y, _z) in enumerate(xyz)},
        }
        groups = {
            "1": {"atom_ids": [1, 2], "origin": [0, 0, 0],
                  "normal": [0, 0, 1]},
            "2": {"atom_ids": [3, 4], "origin": [0, 0, 0],
                  "normal": [0, 1, 0]},
        }
        graph = {0: {1, 2, 3, 4}, 1: {0}, 2: {0}, 3: {0}, 4: {0}}
        self.assertEqual(display_geometry._close_selected_paths({1, 2}, graph), {0, 1, 2})
        self.assertEqual(display_geometry._close_selected_paths({3, 4}, graph), {0, 3, 4})
        with self.assertRaisesRegex(ValueError, "目标平面冲突"):
            apply_plane_groups(record, groups)

    def test_existing_invalid_preview_hotspots_raise_instead_of_fallback(self):
        record = json.loads((ROOT / "测试" / "输出" / "二维拍平长链.json")
                            .read_text(encoding="utf-8"))
        for corrupt in (lambda points: points["0"].__setitem__(0, float("nan")),
                        lambda points: points["0"].__setitem__(0, True),
                        lambda points: points.__setitem__("0", points["1"][:]),
                        lambda points: points.pop("0")):
            broken = copy.deepcopy(record)
            corrupt(broken["thumbnail_atom_positions"])
            with self.subTest(corrupt=corrupt), self.assertRaisesRegex(ValueError, "二维预览"):
                flatten_overrides(broken)

    def test_real_benzyl_alcohol_follows_depiction_and_preserves_oh(self):
        before = copy.deepcopy(self.record)
        result = flatten_overrides(self.record)
        heavy = [atom["id"] for atom in self.record["atoms"] if atom["element"] != "H"]
        self.assertEqual(set(result), {str(atom["id"]) for atom in self.record["atoms"]})
        # A plane through three separated aromatic carbons is independent of
        # the implementation's PCA normal.
        ring = sorted({atom_id for bond in self.record["bonds"] if bond["aromatic"]
                       for atom_id in (bond["a"], bond["b"])})
        self.assertGreaterEqual(len(ring), 6)
        self.assertGreater(distance(result[str(ring[0])], position(self.record, ring[0])), 1e-4)
        origin, normal = display_geometry._plane([result[str(i)] for i in ring])
        for atom_id in heavy:
            delta = [result[str(atom_id)][i]-origin[i] for i in range(3)]
            self.assertLess(abs(sum(delta[i]*normal[i] for i in range(3))), 1e-7)
        oxygen = next(a["id"] for a in self.record["atoms"] if a["element"] == "O")
        oh = next(b["b"] if b["a"] == oxygen else b["a"] for b in self.record["bonds"]
                  if oxygen in (b["a"], b["b"]) and self.record["atoms"][b["b"] if b["a"] == oxygen else b["a"]]["element"] == "H")
        self.assertLess(abs(sum((result[str(oh)][i]-origin[i])*normal[i] for i in range(3))), 1e-7)
        self.assertAlmostEqual(distance(result[str(oxygen)], result[str(oh)]),
                               distance(position(self.record, oxygen), position(self.record, oh)),
                               places=7)
        self.assertEqual(self.record, before)

    def test_saved_benzyl_alcohol_fixture_follows_depiction(self):
        fixture = ROOT / "测试" / "输出" / "苄醇三维.json"
        record = json.loads(fixture.read_text(encoding="utf-8"))
        result = flatten_overrides(record)
        heavy = [atom["id"] for atom in record["atoms"] if atom["element"] != "H"]
        center, plane_normal = display_geometry._plane([result[str(i)] for i in heavy])
        self.assertLess(max(abs(sum((result[str(i)][axis]-center[axis])*plane_normal[axis]
                                    for axis in range(3))) for i in heavy), 1e-7)
        oxygen = next(a["id"] for a in record["atoms"] if a["element"] == "O")
        ring_ids = {i for bond in record["bonds"] if bond["aromatic"]
                    for i in (bond["a"], bond["b"])}
        origin, normal = display_geometry._plane([result[str(i)] for i in sorted(ring_ids)])
        self.assertLess(abs(sum((result[str(oxygen)][i]-origin[i])*normal[i]
                                for i in range(3))), 1e-7)

    def test_nonplanar_ring_is_rejected_without_distortion(self):
        record = {"atoms": [{"id": i, "element": "C", "x": x, "y": y, "z": z}
                            for i, (x, y, z) in enumerate(((1, 0, 0.8), (0, 1, -0.8),
                                                           (-1, 0, 0.8), (0, -1, -0.8)))],
                  "bonds": [{"a": i, "b": (i+1)%4} for i in range(4)]}
        before = copy.deepcopy(record)
        with self.assertRaisesRegex(ValueError, "非平面环"):
            flatten_overrides(record)
        self.assertEqual(record, before)

    def test_local_oxygen_moves_its_rigid_downstream_branch(self):
        oxygen = next(a["id"] for a in self.record["atoms"] if a["element"] == "O")
        hydrogen = next(b["b"] if b["a"] == oxygen else b["a"]
                        for b in self.record["bonds"] if oxygen in (b["a"], b["b"])
                        and self.record["atoms"][b["b"] if b["a"] == oxygen else b["a"]]["element"] == "H")
        existing = {"2": position(self.record, 2)}
        existing_before = copy.deepcopy(existing)
        result = flatten_overrides(self.record, existing, atom_ids=[oxygen, hydrogen])
        self.assertEqual(existing, existing_before)
        self.assertNotEqual(result["2"], existing["2"])
        self.assertEqual(set(result), {str(atom["id"]) for atom in self.record["atoms"]})
        self.assertGreater(distance(result[str(oxygen)], position(self.record, oxygen)), 1e-3)
        attached = next(bond["a"] if bond["b"] == oxygen else bond["b"]
                        for bond in self.record["bonds"] if oxygen in (bond["a"], bond["b"])
                        and hydrogen not in (bond["a"], bond["b"]))
        self.assertAlmostEqual(distance(result[str(oxygen)], result[str(attached)]),
                               distance(position(self.record, oxygen), position(self.record, attached)),
                               places=7)
        ring_ids = sorted({i for bond in self.record["bonds"] if bond["aromatic"]
                           for i in (bond["a"], bond["b"])})
        ring_origin, ring_normal = display_geometry._plane([position(self.record, i)
                                                             for i in ring_ids])
        for atom_id in (oxygen, hydrogen):
            self.assertLess(abs(sum((result[str(atom_id)][i]-ring_origin[i])*ring_normal[i]
                                    for i in range(3))), 1e-7)

    def test_local_benzylic_carbon_carries_oxygen_and_hydrogens(self):
        ring_ids = {i for bond in self.record["bonds"] if bond["aromatic"]
                    for i in (bond["a"], bond["b"])}
        carbon = next(a["id"] for a in self.record["atoms"] if a["element"] == "C"
                      and a["id"] not in ring_ids)
        oxygen = next(a["id"] for a in self.record["atoms"] if a["element"] == "O")
        result = flatten_overrides(self.record, atom_ids=[carbon])
        self.assertIn(str(oxygen), result)
        self.assertTrue(any(str(n) in result for bond in self.record["bonds"]
                            for n in (bond["a"], bond["b"])
                            if carbon in (bond["a"], bond["b"]) and
                            self.record["atoms"][n]["element"] == "H"))
        self.assertTrue(any(distance(result[str(atom_id)], position(self.record, atom_id)) > 1e-4
                            for atom_id in ring_ids))
        for a in ring_ids:
            for b in ring_ids:
                self.assertAlmostEqual(distance(result[str(a)], result[str(b)]),
                                       distance(position(self.record, a), position(self.record, b)),
                                       places=7)

    def test_invalid_selection_and_plane(self):
        hydrogen = next(a["id"] for a in self.record["atoms"] if a["element"] == "H")
        for ids, pattern in (([9999], "未知"), ([hydrogen], "氢"), ([], "重原子")):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, pattern):
                flatten_overrides(self.record, atom_ids=ids)
        with self.assertRaisesRegex(ValueError, "未知平面"):
            flatten_overrides(self.record, plane="bad")

    def test_two_atoms_keep_original_bond_even_for_perpendicular_plane(self):
        record = {"atoms": [{"id": 0, "element": "C", "x": 0, "y": 0, "z": -1},
                            {"id": 1, "element": "C", "x": 0, "y": 0, "z": 1}],
                  "bonds": [{"a": 0, "b": 1}]}
        flat = flatten_overrides(record, plane="xy")
        self.assertEqual(flat["0"], [0.0, 0.0, -1.0])
        self.assertAlmostEqual(flat["1"][2], 0.0)
        assert_bonds_preserved(self, record, flat)
        self.assertGreater(distance(*flatten_overrides(record, plane="xz").values()), 1.9)

    def test_auto_fallback_for_one_or_two_heavy_atoms(self):
        one = {"atoms": [{"id": 0, "element": "He", "x": 2, "y": -1, "z": 3}], "bonds": []}
        self.assertEqual(flatten_overrides(one), {"0": [2.0, -1.0, 3.0]})
        two = {"atoms": [{"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
                         {"id": 1, "element": "O", "x": 1, "y": 2, "z": 3}],
               "bonds": [{"a": 0, "b": 1}]}
        self.assertEqual(flatten_overrides(two), {"0": [0.0, 0.0, 0.0], "1": [1.0, 2.0, 3.0]})

    def test_consecutive_local_planes_use_current_display_positions(self):
        oxygen = next(a["id"] for a in self.record["atoms"] if a["element"] == "O")
        hydrogen = next(b["b"] if b["a"] == oxygen else b["a"]
                        for b in self.record["bonds"] if oxygen in (b["a"], b["b"])
                        and self.record["atoms"][b["b"] if b["a"] == oxygen else b["a"]]["element"] == "H")
        original = copy.deepcopy(self.record)
        first = flatten_overrides(self.record, atom_ids=[oxygen], plane="xy")
        second = flatten_overrides(self.record, first, atom_ids=[oxygen], plane="xz")
        self.assertNotEqual(second[str(oxygen)], first[str(oxygen)])
        self.assertNotAlmostEqual(second[str(oxygen)][2], position(self.record, oxygen)[2])
        self.assertEqual(set(second), {str(atom["id"]) for atom in self.record["atoms"]})
        self.assertAlmostEqual(distance(second[str(oxygen)], second[str(hydrogen)]),
                               distance(position(self.record, oxygen), position(self.record, hydrogen)),
                               places=7)
        self.assertEqual(self.record, original)

    def test_cycle_basis_bounds_dense_graph_candidates(self):
        count = 12
        atoms = [{"id": i, "element": "C", "x": math.cos(2*math.pi*i/count),
                  "y": math.sin(2*math.pi*i/count), "z": 0.0} for i in range(count)]
        bonds = [{"a": i, "b": j} for i in range(count) for j in range(i+1, count)]
        record = {"atoms": atoms, "bonds": bonds}
        original_plane = display_geometry._plane
        with patch.object(display_geometry, "_plane", wraps=original_plane) as fitted:
            result = flatten_overrides(record)
        self.assertEqual(len(result), count)
        # A connected graph has exactly E-V+1 non-tree edges. No simple-cycle
        # expansion may add more PCA fits than this bounded cycle basis.
        self.assertLessEqual(fitted.call_count, len(bonds)-count+1)

    def test_plane_group_uses_selected_origin_and_original_ring_normal(self):
        oxygen = next(a["id"] for a in self.record["atoms"] if a["element"] == "O")
        sidechain = next(b["b"] if b["a"] == oxygen else b["a"]
                         for b in self.record["bonds"] if oxygen in (b["a"], b["b"])
                         and self.record["atoms"][b["b"] if b["a"] == oxygen else b["a"]]["element"] == "C")
        group = make_plane_group(self.record, [oxygen, sidechain])
        self.assertEqual(group["atom_ids"], sorted([oxygen, sidechain]))
        for axis in range(3):
            self.assertAlmostEqual(group["origin"][axis],
                                   (position(self.record, oxygen)[axis] +
                                    position(self.record, sidechain)[axis]) / 2)
        self.assertAlmostEqual(math.sqrt(sum(v*v for v in group["normal"])), 1.0)
        ring_members = sorted({i for bond in self.record["bonds"] if bond["aromatic"]
                               for i in (bond["a"], bond["b"])})
        ring_group = make_plane_group(self.record, ring_members)
        self.assertAlmostEqual(abs(sum(a*b for a, b in zip(group["normal"],
                                                          ring_group["normal"]))), 1.0)

    def test_plane_group_with_ring_and_oxygen_keeps_ring_normal(self):
        ring_ids = sorted({i for bond in self.record["bonds"] if bond["aromatic"]
                           for i in (bond["a"], bond["b"])})
        oxygen = next(a["id"] for a in self.record["atoms"] if a["element"] == "O")
        ring_group = make_plane_group(self.record, ring_ids)
        combined = make_plane_group(self.record, ring_ids + [oxygen])
        self.assertAlmostEqual(abs(sum(a*b for a, b in zip(combined["normal"],
                                                          ring_group["normal"]))), 1.0)
        for left, right in zip(combined["origin"], ring_group["origin"]):
            self.assertAlmostEqual(left, right)
        result = apply_plane_groups(self.record, {"1": combined})
        for atom_id in ring_ids + [oxygen]:
            self.assertLess(abs(sum((result[str(atom_id)][axis]-ring_group["origin"][axis])*
                                    ring_group["normal"][axis] for axis in range(3))), 1e-7)

    def test_terminal_carbon_hydrogens_keep_spatial_geometry(self):
        record = {"atoms": [{"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
                            {"id": 1, "element": "C", "x": 1, "y": 0, "z": 1},
                            {"id": 2, "element": "H", "x": 1, "y": 1, "z": 2},
                            {"id": 3, "element": "H", "x": 1, "y": -1, "z": 1},
                            {"id": 4, "element": "H", "x": 2, "y": 0, "z": 2}],
                  "bonds": [{"a": 0, "b": 1}, {"a": 1, "b": 2},
                            {"a": 1, "b": 3}, {"a": 1, "b": 4}]}
        result = flatten_overrides(record, plane="xy")
        self.assertAlmostEqual(result["1"][2], 0.5)
        self.assertTrue(any(abs(result[str(i)][2]-0.5) > 0.1 for i in (2, 3, 4)))
        assert_bonds_preserved(self, record, result)
        for a, b in ((2, 3), (2, 4), (3, 4)):
            self.assertAlmostEqual(distance(result[str(a)], result[str(b)]),
                                   distance(position(record, a), position(record, b)))

    def test_multiple_groups_preserve_ring_and_reject_branch_conflicts(self):
        record = copy.deepcopy(self.record)
        ring_ids = sorted({i for bond in record["bonds"] if bond["aromatic"]
                           for i in (bond["a"], bond["b"])})
        oxygen = next(a["id"] for a in record["atoms"] if a["element"] == "O")
        ring_group = make_plane_group(record, ring_ids)
        oxygen_group = make_plane_group(record, [oxygen])
        oxygen_group["origin"] = ring_group["origin"][:]
        oxygen_group["normal"] = ring_group["normal"][:]
        result = apply_plane_groups(record, {"1": ring_group, "2": oxygen_group})
        self.assertGreater(distance(result[str(oxygen)], position(record, oxygen)), 1e-3)
        for atom_id in ring_ids:
            self.assertLess(abs(sum((result[str(atom_id)][axis]-ring_group["origin"][axis])*
                                    ring_group["normal"][axis] for axis in range(3))), 1e-7)
        self.assertEqual(record, self.record)

        chain = {"atoms": [{"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
                           {"id": 1, "element": "C", "x": 1, "y": 0, "z": 1},
                           {"id": 2, "element": "O", "x": 2, "y": 1, "z": 2}],
                 "bonds": [{"a": 0, "b": 1}, {"a": 1, "b": 2}]}
        groups = {"1": {"atom_ids": [2], "origin": [0, 0, 0], "normal": [0, 0, 1]},
                  "2": {"atom_ids": [1], "origin": [0, 0, 0], "normal": [0, 0, 1]}}
        with self.assertRaisesRegex(ValueError, "支链相交"):
            apply_plane_groups(chain, groups)

    def test_plane_groups_reject_overlap_and_invalid_normal(self):
        record = {"atoms": [{"id": 0, "element": "C", "x": 0, "y": 0, "z": 1},
                            {"id": 1, "element": "C", "x": 2, "y": 0, "z": 2}],
                  "bonds": [{"a": 0, "b": 1}]}
        group = {"atom_ids": [0], "origin": [0, 0, 0], "normal": [0, 0, 1]}
        with self.assertRaisesRegex(ValueError, "多个平面组"):
            apply_plane_groups(record, {"1": group, "2": group})
        with self.assertRaisesRegex(ValueError, "法线不能为零"):
            apply_plane_groups(record, {"1": {**group, "normal": [0, 0, 0]}})
        with self.assertRaisesRegex(ValueError, "重原子"):
            apply_plane_groups(record, {"1": {**group, "atom_ids": [0, 0]}})


if __name__ == "__main__":
    unittest.main()
