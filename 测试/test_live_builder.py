"""Live preview keeps C4D object identity and refuses edited descendants."""

import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Vector:
    def __init__(self, x=0, y=None, z=None):
        self.x, self.y, self.z = float(x), float(x if y is None else y), float(x if z is None else z)

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        return Vector(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, factor):
        return Vector(self.x * factor, self.y * factor, self.z * factor)

    __rmul__ = __mul__

    def Dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def Cross(self, other):
        return Vector(self.y * other.z - self.z * other.y,
                      self.z * other.x - self.x * other.z,
                      self.x * other.y - self.y * other.x)

    def GetLength(self):
        return self.Dot(self) ** .5

    def GetNormalized(self):
        return self * (1 / self.GetLength())

    def Normalize(self):
        normal = self.GetNormalized()
        self.x, self.y, self.z = normal.x, normal.y, normal.z


class Matrix:
    def __init__(self, *, off=None, v1=None, v2=None, v3=None):
        self.off, self.v1, self.v2, self.v3 = off, v1, v2, v3


class Object:
    def __init__(self, name, children=()):
        self.name = name
        self.children = list(children)
        self.values = {}
        self.position = Vector(0)
        self.scale = Vector(1)
        self.matrix = Matrix()
        self.meta = None

    def GetName(self): return self.name
    def GetDown(self): return self.children[0] if self.children else None
    def GetNext(self): return getattr(self, "next", None)
    def GetRelPos(self): return self.position
    def SetRelPos(self, value): self.position = value
    def GetRelScale(self): return self.scale
    def SetRelScale(self, value): self.scale = value
    def GetMl(self): return self.matrix
    def SetMl(self, value): self.matrix = value
    def __getitem__(self, key): return self.values[key]
    def __setitem__(self, key, value): self.values[key] = value


def group(name, nodes):
    result = Object(name, nodes)
    for one, following in zip(result.children, result.children[1:]):
        one.next = following
    return result


class Document:
    def __init__(self):
        self.undo = []
        self.events = 0

    def StartUndo(self): return True
    def EndUndo(self): pass
    def AddUndo(self, kind, obj):
        self.undo.append(obj)
        return True


class LiveBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c4d = types.ModuleType("c4d")
        c4d.Vector, c4d.Matrix = Vector, Matrix
        c4d.UNDOTYPE_CHANGE = 99
        c4d.UNDOTYPE_CHANGE_SMALL = 100
        for i, name in enumerate(("PRIM_SPHERE_RAD", "PRIM_SPHERE_SUB",
                                  "PRIM_CYLINDER_RADIUS", "PRIM_CYLINDER_SEG",
                                  "PRIM_CYLINDER_CAPS"), 200):
            setattr(c4d, name, i)
        c4d.EventAdd = lambda: None
        maxon = types.ModuleType("maxon")
        maxon.Id = str
        cls.stub = patch.dict(sys.modules, {"c4d": c4d, "maxon": maxon})
        cls.stub.start()
        sys.modules.pop("scimol_c4d.c4d_builder", None)
        cls.builder = importlib.import_module("scimol_c4d.c4d_builder")
        cls.c4d = c4d

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("scimol_c4d.c4d_builder", None)
        cls.stub.stop()

    def test_live_geometry_keeps_children_and_changes_dimensions(self):
        from scimol_c4d.records import normalized_style
        record = {"name": "C-O", "atoms": [
            {"id": 0, "element": "C", "x": 0, "y": 0, "z": 0},
            {"id": 1, "element": "O", "x": 1, "y": 0, "z": 0}],
            "bonds": [{"a": 0, "b": 1, "order": 1}]}
        old = normalized_style({"bond_material": "uniform", "representation": "continuous"})
        new = normalized_style({**old, "atom_radius": .7, "bond_radius": .12,
                                "bond_caps": False, "orientation": "xy",
                                "center_atom_ids": [1]})
        carbon, oxygen = Object("原子_C_0"), Object("原子_O_1")
        strand = Object("键_0_1_1")
        c_proto, o_proto, b_proto = Object("球母体_C"), Object("球母体_O"), Object("键母体_uniform")
        for proto in (c_proto, o_proto):
            proto[self.c4d.PRIM_SPHERE_RAD] = 15
            proto[self.c4d.PRIM_SPHERE_SUB] = 24
        b_proto[self.c4d.PRIM_CYLINDER_RADIUS] = 4
        b_proto[self.c4d.PRIM_CYLINDER_SEG] = 24
        b_proto[self.c4d.PRIM_CYLINDER_CAPS] = True
        root = group("root", [group("原子", [carbon, oxygen]),
                              group("化学键", [strand]),
                              group("几何母体", [c_proto, o_proto, b_proto])])
        doc = Document()
        with (patch.object(self.builder, "_get_meta", return_value={"original": True}),
              patch.object(self.builder, "_put_meta") as put,
              patch.object(self.builder, "_signature", return_value="new-signature")):
            self.assertTrue(self.builder._update_live_geometry(doc, root, record, old, new))
        self.assertIs(root.GetDown().GetDown(), carbon)
        self.assertIs(root.GetDown().GetNext().GetDown(), strand)
        self.assertAlmostEqual(oxygen.position.GetLength(), 0)
        self.assertAlmostEqual(c_proto[self.c4d.PRIM_SPHERE_RAD], .7 * 50 *
                               self.builder._atom_factor(new, "C"))
        self.assertAlmostEqual(b_proto[self.c4d.PRIM_CYLINDER_RADIUS], 6)
        self.assertFalse(b_proto[self.c4d.PRIM_CYLINDER_CAPS])
        self.assertAlmostEqual(strand.matrix.v2.GetLength(), 50)
        self.assertEqual(len(doc.undo), 7)
        self.assertEqual(put.call_args.args[1]["signature"], "new-signature")
        later = normalized_style({**new, "bond_spacing": .32, "atom_radius": .45,
                                  "center_atom_ids": [0]})
        with (patch.object(self.builder, "_get_meta", return_value={"original": True}),
              patch.object(self.builder, "_put_meta"),
              patch.object(self.builder, "_signature", return_value="later-signature")):
            self.assertTrue(self.builder._update_live_geometry(doc, root, record, new, later))
        self.assertIs(root.GetDown().GetDown(), carbon)
        self.assertAlmostEqual(carbon.position.GetLength(), 0)
        self.assertAlmostEqual(oxygen.position.GetLength(), 50)
        self.assertAlmostEqual(c_proto[self.c4d.PRIM_SPHERE_RAD], .45 * 50 *
                               self.builder._atom_factor(later, "C"))
        self.assertAlmostEqual(strand.matrix.v2.GetLength(), 50)

    def test_topology_change_requires_guarded_rebuild(self):
        from scimol_c4d.records import normalized_style
        old = normalized_style()
        new = normalized_style({**old, "bond_material": "uniform"})
        with patch.object(self.builder, "_material_specs", side_effect=AssertionError("must not plan")):
            self.assertIsNone(self.builder._live_plan(Object("root"), {}, old, new))

    def test_material_scope_prevents_cross_model_reuse(self):
        color = [0.18, 0.18, 0.18]
        token = self.builder._material_spec_key(("atom", "C"), color)
        global_mat = types.SimpleNamespace(scope=None)
        isolated_mat = types.SimpleNamespace(scope="preview-a")
        global_mat.GetNext = lambda: isolated_mat
        isolated_mat.GetNext = lambda: None
        doc = types.SimpleNamespace(GetFirstMaterial=lambda: global_mat)
        global_mat.GetDocument = isolated_mat.GetDocument = lambda: doc
        with (patch.object(self.builder, "_get_material_spec", return_value=token),
              patch.object(self.builder, "_material_scope", side_effect=lambda mat: mat.scope)):
            self.assertEqual(self.builder._reusable_materials(
                doc, {("atom", "C"): color}), {("atom", "C"): global_mat})
            self.assertEqual(self.builder._reusable_materials(
                doc, {("atom", "C"): color}, "preview-a"),
                {("atom", "C"): isolated_mat})
            self.assertEqual(self.builder._reusable_materials(
                doc, {("atom", "C"): color}, "preview-b"), {})

    def test_private_color_edits_existing_material_without_rebuilding_geometry(self):
        from scimol_c4d.records import normalized_style
        record = {"name": "C", "atoms": [{"id": 0, "element": "C",
                  "x": 0, "y": 0, "z": 0}], "bonds": []}
        old = normalized_style({"inherit_materials": False})
        new = normalized_style({**old, "element_colors": {"C": [.4, .3, .2]}})
        root, doc, carbon_mat = Object("root"), Document(), Object("material")
        old_token = self.builder._material_spec_key(("atom", "C"),
                                                     self.builder._material_specs(record, old)[("atom", "C")])
        with (patch.object(self.builder, "_prototype_materials",
                           return_value={("atom", "C"): carbon_mat}),
              patch.object(self.builder, "_material_scope", return_value="preview-a"),
              patch.object(self.builder, "_get_material_spec", return_value=old_token),
              patch.object(self.builder, "_material_used_outside_root", return_value=False),
              patch.object(self.builder, "_get_meta", return_value={"material_scope": "preview-a"}),
              patch.object(self.builder, "_signature", return_value="new-signature"),
              patch.object(self.builder, "_set_material_color") as set_color,
              patch.object(self.builder, "_set_material_spec") as set_spec,
              patch.object(self.builder, "_put_meta") as put):
            self.assertTrue(self.builder._update_live_private_colors(
                doc, root, record, old, new, "preview-a"))
        set_color.assert_called_once_with(carbon_mat, [.4, .3, .2], record_undo=False)
        set_spec.assert_called_once_with(carbon_mat, ("atom", "C"),
                                         [.4, .3, .2], "preview-a")
        self.assertEqual(doc.undo, [root, carbon_mat])
        self.assertEqual(put.call_args.args[1]["material_scope"], "preview-a")


if __name__ == "__main__":
    unittest.main()
