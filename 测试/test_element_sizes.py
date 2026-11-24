"""Element radius validation and geometry behavior with local C4D test doubles."""

import json
import unittest
from unittest.mock import patch

import test_local_appearance as local_appearance
import test_live_builder as live_builder

from scimol_c4d.records import migrate_element_scales, normalized_style, stable_json


class ElementStyleTests(unittest.TestCase):
    def test_default_and_roundtrip(self):
        old = normalized_style({"atom_radius": .45})
        self.assertEqual(old["element_radius_overrides"], {})
        style = normalized_style({"atom_radius": .45,
                                  "element_radius_overrides": {"C": .8, "H": .2}})
        self.assertEqual(normalized_style(json.loads(stable_json(style))), style)

    def test_reject_invalid_symbols_and_radii(self):
        for entry in ({"c": .4}, {"Xx": .4}, {"C ": .4}, {1: .4},
                      {"C": 0}, {"C": -1}, {"C": True},
                      {"C": float("nan")}, {"C": float("inf")}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                normalized_style({"element_radius_overrides": entry})

    def test_element_scales_validate_and_normalize(self):
        style = normalized_style({"element_scales": {"C": 1, "O": .01, "H": 1e6}})
        self.assertEqual(style["element_scales"], {"O": .01, "H": 1e6})
        self.assertEqual(normalized_style(json.loads(stable_json(style))), style)
        for entry in ({"c": 2}, {"Xx": 2}, {"C ": 2}, {1: 2},
                      {"C": 0}, {"C": -1}, {"C": True},
                      {"C": float("nan")}, {"C": float("inf")}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                normalized_style({"element_scales": entry})

    def test_migration_is_pure_and_retains_other_scales(self):
        original = {"representation": "continuous", "atom_radius": .45,
                    "element_radius_overrides": {"C": .8},
                    "element_scales": {"O": 1.7}}
        migrated = migrate_element_scales(original)
        self.assertEqual(original["element_radius_overrides"], {"C": .8})
        self.assertEqual(migrated["element_radius_overrides"], {})
        self.assertEqual(migrated["element_scales"]["O"], 1.7)
        self.assertEqual(migrate_element_scales(migrated), migrated)


class FreshGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        local_appearance.LocalAppearanceTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        local_appearance.LocalAppearanceTests.tearDownClass.__func__(cls)

    def test_element_radius_and_atom_override_in_continuous_mode(self):
        record = local_appearance.LocalAppearanceTests.molecule()
        original = normalized_style({"representation": "continuous",
                                     "atom_radius_overrides": {"0": .6}})
        changed = normalized_style({**original, "element_radius_overrides": {"C": .8}})
        mats = {("atom", e): object() for e in ("C", "O")}
        mats.update({("bond", e): object() for e in ("C", "O")})
        old_root = self.builder._make_hierarchy(record, original, mats)
        new_root = self.builder._make_hierarchy(record, changed, mats)
        old_atoms = {o.name: o for o in old_root.children[0].children}
        new_atoms = {o.name: o for o in new_root.children[0].children}
        old_protos = {o.name: o for o in old_root.children[2].children}
        new_protos = {o.name: o for o in new_root.children[2].children}
        radius_key = self.c4d.PRIM_SPHERE_RAD
        self.assertAlmostEqual(new_protos["球母体_C"].values[radius_key],
                               .8 * 50 * (1 + (.8 - .3) / .7 * (1.7 - 1)))
        self.assertEqual(old_protos["球母体_O"].values[radius_key],
                         new_protos["球母体_O"].values[radius_key])
        self.assertAlmostEqual(
            old_protos["球母体_C"].values[radius_key] * old_atoms["原子_C_0"].scale.x,
            new_protos["球母体_C"].values[radius_key] * new_atoms["原子_C_0"].scale.x)
        self.assertEqual(new_atoms["原子_C_1"].scale.x, 1.0)
        old_bonds = {obj.name: obj for obj in old_root.children[1].children}
        new_bonds = {obj.name: obj for obj in new_root.children[1].children}
        for name, new in new_bonds.items():
            self.assertAlmostEqual(old_bonds[name].matrix.v1.GetLength(),
                                   new.matrix.v1.GetLength())
            if name.endswith("_A"):
                mate = name[:-2] + "_B"
                self.assertAlmostEqual(
                    old_bonds[name].matrix.v2.GetLength() + old_bonds[mate].matrix.v2.GetLength(),
                    new.matrix.v2.GetLength() + new_bonds[mate].matrix.v2.GetLength())

    def test_global_radius_does_not_change_independent_element(self):
        old = normalized_style({"representation": "continuous",
                                "element_radius_overrides": {"C": .8}})
        new = normalized_style({**old, "atom_radius": .6})
        self.assertEqual(self.builder._sphere_radius(old, "C"),
                         self.builder._sphere_radius(new, "C"))
        self.assertNotEqual(self.builder._sphere_radius(old, "O"),
                            self.builder._sphere_radius(new, "O"))

    def test_relative_scale_follows_global_size_after_representation_mapping(self):
        for representation in ("ball_stick", "continuous", "space_fill"):
            with self.subTest(representation=representation):
                base = normalized_style({"representation": representation,
                                         "atom_radius": .45})
                changed = normalized_style({**base, "element_scales": {"C": 1.8}})
                self.assertAlmostEqual(self.builder._sphere_radius(changed, "C"),
                                       self.builder._sphere_radius(base, "C") * 1.8)
                self.assertEqual(self.builder._sphere_radius(changed, "O"),
                                 self.builder._sphere_radius(base, "O"))
                larger = normalized_style({**changed, "atom_radius": .6})
                self.assertGreater(self.builder._sphere_radius(larger, "C"),
                                   self.builder._sphere_radius(changed, "C"))

    def test_legacy_migration_preserves_final_radius_and_atom_override(self):
        atom = {"id": 0, "element": "C"}
        for representation in ("ball_stick", "continuous", "space_fill"):
            with self.subTest(representation=representation):
                old = normalized_style({"representation": representation,
                                        "atom_radius": .45,
                                        "element_radius_overrides": {"C": .8},
                                        "atom_radius_overrides": {"0": .6}})
                new = migrate_element_scales(old)
                self.assertAlmostEqual(self.builder._sphere_radius(old, "C"),
                                       self.builder._sphere_radius(new, "C"))
                self.assertAlmostEqual(
                    self.builder._sphere_radius(old, "C") *
                    self.builder._atom_instance_scale(old, atom),
                    self.builder._sphere_radius(new, "C") *
                    self.builder._atom_instance_scale(new, atom))
                self.assertEqual(old["sphere_segments"], new["sphere_segments"])


class LiveElementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        live_builder.LiveBuilderTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        live_builder.LiveBuilderTests.tearDownClass.__func__(cls)

    def test_only_changed_element_and_its_overridden_instance_are_edited(self):
        record = {"name": "CO", "atoms": [
            {"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
            {"id": 1, "element": "C", "x": 1, "y": 0, "z": 0},
            {"id": 2, "element": "O", "x": 2, "y": 0, "z": 0}], "bonds": []}
        old = normalized_style({"representation": "continuous",
                                "atom_radius_overrides": {"0": .6}})
        new = normalized_style({**old, "element_radius_overrides": {"C": .8}})
        atom0, atom1, atom2 = (live_builder.Object("原子_%s_%s" % (a["element"], a["id"]))
                               for a in record["atoms"])
        proto_c, proto_o, bond_c, bond_o = (live_builder.Object(name) for name in
            ("球母体_C", "球母体_O", "键母体_C", "键母体_O"))
        root = live_builder.group("root", [live_builder.group("原子", [atom0, atom1, atom2]),
                                         live_builder.group("化学键", []),
                                         live_builder.group("几何母体", [proto_c, proto_o, bond_c, bond_o])])
        operations = self.builder._live_plan(root, record, old, new)
        self.assertEqual({obj for obj, _fields in operations}, {atom0, proto_c})
        self.assertAlmostEqual(self.builder.atom_radius_for_element(new, "C"), .8)
        self.assertAlmostEqual(self.builder.atom_radius_for_element(new, "O"), .3)
        proto_c[self.c4d.PRIM_SPHERE_RAD] = self.builder._sphere_radius(old, "C")
        proto_c[self.c4d.PRIM_SPHERE_SUB] = 24
        atom0.scale = self.c4d.Vector(self.builder._atom_instance_scale(old, record["atoms"][0]))
        with (patch.object(self.builder, "_get_meta", return_value={"record": record}),
              patch.object(self.builder, "_put_meta"),
              patch.object(self.builder, "_signature", return_value="signature")):
            self.assertTrue(self.builder._update_live_geometry(live_builder.Document(), root, record, old, new))
        self.assertAlmostEqual(proto_c[self.c4d.PRIM_SPHERE_RAD] * atom0.scale.x,
                               .6 * 50 * self.builder._atom_factor(old, "C"))
        self.assertEqual(atom1.scale.x, 1)
        self.assertEqual(atom2.scale.x, 1)

    def test_ball_stick_to_continuous_updates_same_objects_and_color_split(self):
        record = {"name": "CH", "atoms": [
            {"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
            {"id": 1, "element": "H", "x": 2, "y": 0, "z": 0}],
            "bonds": [{"a": 0, "b": 1, "order": 1}]}
        old = normalized_style({"representation": "ball_stick"})
        new = normalized_style({**old, "representation": "continuous", "atom_radius": .6})
        carbon, hydrogen = (live_builder.Object("原子_C_0"), live_builder.Object("原子_H_1"))
        bond_a, bond_b = (live_builder.Object("键_0_1_1_A"),
                          live_builder.Object("键_0_1_1_B"))
        proto_c, proto_h = (live_builder.Object("球母体_C"),
                            live_builder.Object("球母体_H"))
        bond_c, bond_h = (live_builder.Object("键母体_C"),
                          live_builder.Object("键母体_H"))
        for element, proto in (("C", proto_c), ("H", proto_h)):
            proto[self.c4d.PRIM_SPHERE_RAD] = self.builder._sphere_radius(old, element)
            proto[self.c4d.PRIM_SPHERE_SUB] = old["sphere_segments"]
        root = live_builder.group("root", [
            live_builder.group("原子", [carbon, hydrogen]),
            live_builder.group("化学键", [bond_a, bond_b]),
            live_builder.group("几何母体", [proto_c, proto_h, bond_c, bond_h])])
        old_positions = self.builder._geometry_positions(record, old)
        old_segments = list(self.builder._bond_geometry(record, old, old_positions, {0, 1}))
        for obj, segment in zip((bond_a, bond_b), old_segments):
            _name, _key, start, end, thickness = segment
            obj.SetMl(self.builder._segment_matrix(start, end, thickness))
        previous_children = (root.GetDown(), carbon, hydrogen, bond_a, bond_b,
                             proto_c, proto_h, bond_c, bond_h)
        with (patch.object(self.builder, "_get_meta", return_value={"record": record}),
              patch.object(self.builder, "_put_meta"),
              patch.object(self.builder, "_signature", return_value="signature")):
            self.assertTrue(self.builder._update_live_geometry(
                live_builder.Document(), root, record, old, new))
        self.assertIs(root.GetDown(), previous_children[0])
        self.assertEqual((carbon, hydrogen, bond_a, bond_b, proto_c, proto_h,
                          bond_c, bond_h), previous_children[1:])
        self.assertAlmostEqual(proto_c[self.c4d.PRIM_SPHERE_RAD],
                               self.builder._sphere_radius(new, "C"))
        self.assertAlmostEqual(bond_a.matrix.v2.GetLength() +
                               bond_b.matrix.v2.GetLength(), 100)
        self.assertNotAlmostEqual(bond_a.matrix.v2.GetLength(),
                                  bond_b.matrix.v2.GetLength())

    def test_element_change_updates_only_adjacent_colored_bond_instances(self):
        record = {"name": "two", "atoms": [
            {"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
            {"id": 1, "element": "H", "x": 2, "y": 0, "z": 0},
            {"id": 2, "element": "O", "x": 5, "y": 0, "z": 0},
            {"id": 3, "element": "O", "x": 7, "y": 0, "z": 0}],
            "bonds": [{"a": 0, "b": 1, "order": 1},
                       {"a": 2, "b": 3, "order": 1}]}
        old = normalized_style()
        new = normalized_style({**old, "element_radius_overrides": {"C": .6}})
        atom_names = ["原子_C_0", "原子_H_1", "原子_O_2", "原子_O_3"]
        bond_names = ["键_0_1_1_A", "键_0_1_1_B", "键_2_3_1_A", "键_2_3_1_B"]
        proto_names = ["球母体_C", "球母体_H", "球母体_O",
                       "键母体_C", "键母体_H", "键母体_O"]
        root = live_builder.group("root", [
            live_builder.group("原子", [live_builder.Object(n) for n in atom_names]),
            live_builder.group("化学键", [live_builder.Object(n) for n in bond_names]),
            live_builder.group("几何母体", [live_builder.Object(n) for n in proto_names])])
        changes = self.builder._live_plan(root, record, old, new)
        self.assertEqual({obj.GetName() for obj, _fields in changes},
                         {"球母体_C", "键_0_1_1_A", "键_0_1_1_B"})
        old_uniform = normalized_style({"bond_material": "uniform"})
        new_uniform = normalized_style({**old_uniform,
                                        "element_radius_overrides": {"C": .6}})
        uniform_root = live_builder.group("root", [
            live_builder.group("原子", [live_builder.Object(n) for n in atom_names]),
            live_builder.group("化学键", [live_builder.Object("键_0_1_1"),
                                          live_builder.Object("键_2_3_1")]),
            live_builder.group("几何母体", [live_builder.Object(n) for n in
                                                proto_names[:3] + ["键母体_uniform"]])])
        changes = self.builder._live_plan(uniform_root, record, old_uniform, new_uniform)
        self.assertEqual({obj.GetName() for obj, _fields in changes}, {"球母体_C"})

    def test_relative_scale_edits_only_affected_prototype_and_bond_split(self):
        record = {"name": "two", "atoms": [
            {"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
            {"id": 1, "element": "H", "x": 2, "y": 0, "z": 0},
            {"id": 2, "element": "O", "x": 5, "y": 0, "z": 0},
            {"id": 3, "element": "O", "x": 7, "y": 0, "z": 0},
            {"id": 4, "element": "C", "x": 3, "y": 0, "z": 0}],
            "bonds": [{"a": 0, "b": 1, "order": 1},
                       {"a": 2, "b": 3, "order": 1},
                       {"a": 1, "b": 4, "order": 1}]}
        old = normalized_style({"atom_radius_overrides": {"0": .6}})
        new = normalized_style({**old, "element_scales": {"C": 1.7}})
        atom_names = ["原子_C_0", "原子_H_1", "原子_O_2", "原子_O_3", "原子_C_4"]
        bond_names = ["键_0_1_1_A", "键_0_1_1_B", "键_2_3_1_A", "键_2_3_1_B",
                      "键_1_4_1_A", "键_1_4_1_B"]
        proto_names = ["球母体_C", "球母体_H", "球母体_O",
                       "键母体_C", "键母体_H", "键母体_O"]
        root = live_builder.group("root", [
            live_builder.group("原子", [live_builder.Object(n) for n in atom_names]),
            live_builder.group("化学键", [live_builder.Object(n) for n in bond_names]),
            live_builder.group("几何母体", [live_builder.Object(n) for n in proto_names])])
        original_children = tuple(root.children)
        atoms = root.children[0].children
        bonds = root.children[1].children
        prototypes = root.children[2].children
        atoms[0].scale = self.c4d.Vector(self.builder._atom_instance_scale(old, record["atoms"][0]))
        prototypes[0][self.c4d.PRIM_SPHERE_RAD] = self.builder._sphere_radius(old, "C")
        for obj, segment in zip(bonds, self.builder._bond_geometry(
                record, old, self.builder._geometry_positions(record, old), {0, 1, 2, 3, 4})):
            _name, _key, start, end, thickness = segment
            obj.SetMl(self.builder._segment_matrix(start, end, thickness))
        original_ids = tuple(id(obj) for group in root.children for obj in group.children)
        original_lengths = {bond.GetName(): bond.matrix.v2.GetLength() for bond in bonds}
        changes = self.builder._live_plan(root, record, old, new)
        self.assertEqual({obj.GetName() for obj, _fields in changes},
                         {"球母体_C", "原子_C_0", "键_1_4_1_A", "键_1_4_1_B"})
        with (patch.object(self.builder, "_get_meta", return_value={"record": record}),
              patch.object(self.builder, "_put_meta"),
              patch.object(self.builder, "_signature", return_value="signature")):
            self.assertTrue(self.builder._update_live_geometry(
                live_builder.Document(), root, record, old, new))
        self.assertEqual(tuple(root.children), original_children)
        self.assertEqual(tuple(id(obj) for group in root.children for obj in group.children),
                         original_ids)
        self.assertAlmostEqual(prototypes[0][self.c4d.PRIM_SPHERE_RAD] * atoms[0].scale.x,
                               .6 * 50 * self.builder._atom_factor(old, "C"))
        self.assertAlmostEqual(bonds[4].matrix.v2.GetLength() +
                               bonds[5].matrix.v2.GetLength(),
                               original_lengths[bond_names[4]] + original_lengths[bond_names[5]])
        self.assertEqual({bond.GetName(): bond.matrix.v2.GetLength() for bond in bonds[:4]},
                         {name: original_lengths[name] for name in bond_names[:4]})


if __name__ == "__main__":
    unittest.main()
