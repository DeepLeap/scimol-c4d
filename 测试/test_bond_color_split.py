"""The visible portions of an element-colored bond meet near their midpoint."""

import math
import unittest

import test_local_appearance as local_appearance

from scimol_c4d.records import normalized_style


class BondColorSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        local_appearance.LocalAppearanceTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        local_appearance.LocalAppearanceTests.tearDownClass.__func__(cls)

    def segments(self, first="C", second="H", *, length=2.0, order=1, style=None):
        record = {"atoms": [
            {"id": 0, "element": first, "x": 0, "y": 0, "z": 0},
            {"id": 1, "element": second, "x": length, "y": 0, "z": 0}],
            "bonds": [{"a": 0, "b": 1, "order": order}]}
        style = normalized_style({"orientation": "original", **(style or {})})
        positions = {0: self.c4d.Vector(0, 0, 0),
                     1: self.c4d.Vector(length * style["scale"], 0, 0)}
        return record, style, list(self.builder._bond_geometry(record, style, positions, {0, 1}))

    def test_ch_visible_lengths_balance_without_moving_outer_endpoints(self):
        record, style, pieces = self.segments()
        self.assertEqual(len(pieces), 2)
        _name_a, _key_a, start, junction_a, _scale_a = pieces[0]
        _name_b, _key_b, junction_b, end, _scale_b = pieces[1]
        self.assertAlmostEqual(start.x, 0)
        self.assertAlmostEqual(end.x, 100)
        self.assertAlmostEqual(junction_a.x, junction_b.x)
        radius_a = self.builder._sphere_radius(style, "C")
        radius_b = self.builder._sphere_radius(style, "H")
        self.assertAlmostEqual(junction_a.x - radius_a, 100 - radius_b - junction_b.x)

    def test_reversing_elements_reverses_junction_shift(self):
        _record, _style, first = self.segments("C", "H")
        _record, _style, second = self.segments("H", "C")
        self.assertAlmostEqual(first[0][3].x + second[0][3].x, 100)

    def test_same_element_local_radius_override_moves_split(self):
        _record, style, pieces = self.segments(
            "C", "C", style={"atom_radius_overrides": {"0": .5, "1": .2}})
        left = self.builder._sphere_radius(style, "C") * .5 / .3
        right = self.builder._sphere_radius(style, "C") * .2 / .3
        self.assertAlmostEqual(pieces[0][3].x - left,
                               100 - right - pieces[1][2].x)
        self.assertGreater(pieces[0][3].x, 50)

    def test_multiple_bond_offsets_use_sphere_cross_section(self):
        _record, style, pieces = self.segments(order=2)
        self.assertEqual(len(pieces), 4)
        offset = style["bond_spacing"] * style["scale"] / 2
        carbon_cut = math.sqrt(self.builder._sphere_radius(style, "C") ** 2 - offset ** 2)
        hydrogen_cut = math.sqrt(self.builder._sphere_radius(style, "H") ** 2 - offset ** 2)
        for a, b in zip(pieces[::2], pieces[1::2]):
            self.assertAlmostEqual(a[3].x - carbon_cut,
                                   100 - hydrogen_cut - b[2].x)
            self.assertAlmostEqual((a[3] - a[2]).GetLength() +
                                   (b[3] - b[2]).GetLength(), 100)

    def test_overlapping_spheres_fall_back_to_center_and_remain_finite(self):
        _record, _style, pieces = self.segments(
            length=.1, style={"element_radius_overrides": {"C": 1.0, "H": 1.0}})
        self.assertAlmostEqual(pieces[0][3].x, 2.5)
        self.assertTrue(math.isfinite(pieces[0][3].x))
        self.assertGreater((pieces[0][3] - pieces[0][2]).GetLength(), 0)
        self.assertGreater((pieces[1][3] - pieces[1][2]).GetLength(), 0)

    def test_repeated_style_changes_have_no_junction_drift(self):
        base = self.segments(style={"element_radius_overrides": {"C": .6}})[2]
        changed = self.segments(style={"element_radius_overrides": {"C": .9}})[2]
        restored = self.segments(style={"element_radius_overrides": {"C": .6}})[2]
        self.assertNotEqual(base[0][3].x, changed[0][3].x)
        self.assertEqual(base[0][3].x, restored[0][3].x)


if __name__ == "__main__":
    unittest.main()
