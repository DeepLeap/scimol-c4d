"""Per-atom/per-bond radius semantics without launching Cinema 4D."""

import copy
import importlib
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scimol_c4d.records import bond_key, normalized_style


class Vector:
    def __init__(self, x=0.0, y=None, z=None):
        self.x = float(x)
        self.y = float(x if y is None else y)
        self.z = float(x if z is None else z)

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        return Vector(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, number):
        return Vector(self.x * number, self.y * number, self.z * number)

    __rmul__ = __mul__

    def Dot(self, other):
        return self.x*other.x + self.y*other.y + self.z*other.z

    def Cross(self, other):
        return Vector(self.y*other.z - self.z*other.y,
                      self.z*other.x - self.x*other.z,
                      self.x*other.y - self.y*other.x)

    def GetLength(self):
        return math.sqrt(self.Dot(self))

    def GetNormalized(self):
        return self * (1.0 / self.GetLength())

    def Normalize(self):
        normalized = self.GetNormalized()
        self.x, self.y, self.z = normalized.x, normalized.y, normalized.z


class Matrix:
    def __init__(self, *, off=None, v1=None, v2=None, v3=None):
        self.off, self.v1, self.v2, self.v3 = off, v1, v2, v3


class Tag:
    def __init__(self, kind):
        self.kind = kind
        self.values = {}

    def __setitem__(self, key, value):
        self.values[key] = value


class Object:
    def __init__(self, kind):
        self.kind = kind
        self.name = ''
        self.values = {}
        self.children = []
        self.tags = []
        self.position = None
        self.scale = Vector(1)
        self.matrix = None

    def SetName(self, name):
        self.name = name

    def InsertUnderLast(self, parent):
        parent.children.append(self)

    def InsertTag(self, tag):
        self.tags.append(tag)

    def __setitem__(self, key, value):
        self.values[key] = value

    def SetRelPos(self, value):
        self.position = value

    def SetRelScale(self, value):
        self.scale = value

    def SetMl(self, value):
        self.matrix = value


class LocalAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c4d = types.ModuleType('c4d')
        c4d.Vector, c4d.Matrix = Vector, Matrix
        c4d.BaseObject, c4d.BaseTag, c4d.TextureTag = Object, Tag, lambda: Tag(8)
        constants = ('Onull', 'Osphere', 'Ocylinder', 'Oinstance', 'Tphong',
                     'ID_BASEOBJECT_VISIBILITY_EDITOR', 'ID_BASEOBJECT_VISIBILITY_RENDER',
                     'MODE_OFF', 'PRIM_SPHERE_RAD', 'PRIM_SPHERE_SUB',
                     'PRIM_CYLINDER_RADIUS', 'PRIM_CYLINDER_HEIGHT', 'PRIM_CYLINDER_SEG',
                     'PRIM_CYLINDER_CAPS',
                     'INSTANCEOBJECT_LINK', 'INSTANCEOBJECT_RENDERINSTANCE_MODE',
                     'INSTANCEOBJECT_RENDERINSTANCE_MODE_SINGLEINSTANCE',
                     'TEXTURETAG_MATERIAL')
        for index, name in enumerate(constants, 1):
            setattr(c4d, name, index)
        maxon = types.ModuleType('maxon')
        maxon.Id = lambda value: value
        cls.stub = patch.dict(sys.modules, {'c4d': c4d, 'maxon': maxon})
        cls.stub.start()
        sys.modules.pop('scimol_c4d.c4d_builder', None)
        cls.builder = importlib.import_module('scimol_c4d.c4d_builder')
        cls.c4d = c4d

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop('scimol_c4d.c4d_builder', None)
        cls.stub.stop()

    @staticmethod
    def molecule():
        return {'name': '测试', 'atoms': [
            {'id': 0, 'element': 'C', 'x': 0.0, 'y': 0.0, 'z': 0.0},
            {'id': 1, 'element': 'C', 'x': 2.0, 'y': 0.0, 'z': 0.0},
            {'id': 2, 'element': 'O', 'x': 3.0, 'y': 1.0, 'z': 0.0}],
            'bonds': [{'a': 0, 'b': 1, 'order': 2},
                      {'a': 1, 'b': 2, 'order': 1}]}

    def test_canonical_keys_and_invalid_radius_inputs(self):
        self.assertEqual(bond_key(2, 0), '0:2')
        style = normalized_style({'atom_radius_overrides': {'0': 0.6},
                                  'bond_radius_overrides': {'0:1': 0.16}})
        self.assertEqual(style['atom_radius_overrides'], {'0': 0.6})
        self.assertEqual(style['bond_radius_overrides'], {'0:1': 0.16})
        self.assertEqual(normalized_style()['atom_radius_overrides'], {})
        for field, entries in (
                ('atom_radius_overrides', {'01': .2}),
                ('atom_radius_overrides', {'0': True}),
                ('atom_radius_overrides', {'0': float('nan')}),
                ('atom_radius_overrides', {'0': 0}),
                ('bond_radius_overrides', {'1:0': .2}),
                ('bond_radius_overrides', {'0:300': .2}),
                ('bond_radius_overrides', {'0:1': float('inf')})):
            with self.subTest(field=field, entries=entries), self.assertRaises(ValueError):
                normalized_style({field: entries})
        for endpoints in ((True, 1), (1, 1), (-1, 2), (0, 300)):
            with self.subTest(endpoints=endpoints), self.assertRaises(ValueError):
                bond_key(*endpoints)

    def test_missing_atom_or_nonexistent_bond_refused_before_build(self):
        record = self.molecule()
        for style in ({'atom_radius_overrides': {'9': .6}},
                      {'bond_radius_overrides': {'0:2': .16}}):
            with self.subTest(style=style), self.assertRaises(ValueError):
                self.builder._validate_local_radius_targets(record, normalized_style(style))

    def test_overrides_scale_instances_without_changing_lengths_segments_or_materials(self):
        record = self.molecule()
        untouched = copy.deepcopy(record)
        style = normalized_style({'atom_radius_overrides': {'0': .6},
                                  'bond_radius_overrides': {'0:1': .16},
                                  'sphere_segments': 32,
                                  'cylinder_segments': 42})
        mats = {('atom', 'C'): object(), ('atom', 'O'): object(),
                ('bond', 'C'): object(), ('bond', 'O'): object()}
        base = self.builder._make_hierarchy(record, normalized_style(), mats)
        changed = self.builder._make_hierarchy(record, style, mats)
        self.assertEqual(record, untouched)
        atoms_group, bonds_group, templates = changed.children
        atoms = {atom.name: atom for atom in atoms_group.children}
        self.assertEqual(atoms['原子_C_0'].scale.GetLength(), math.sqrt(12))
        self.assertAlmostEqual(atoms['原子_C_1'].scale.GetLength(), math.sqrt(3))
        spheres = [obj for obj in templates.children if obj.kind == self.c4d.Osphere]
        cylinders = [obj for obj in templates.children if obj.kind == self.c4d.Ocylinder]
        self.assertEqual({obj.values[self.c4d.PRIM_SPHERE_SUB] for obj in spheres}, {32})
        self.assertEqual({obj.values[self.c4d.PRIM_CYLINDER_SEG] for obj in cylinders}, {42})
        self.assertEqual(len(templates.children), len(base.children[2].children))
        before = {obj.name: obj for obj in base.children[1].children}
        after = {obj.name: obj for obj in bonds_group.children}
        self.assertEqual(len([name for name in after if name.startswith('键_0_1_')]), 4)
        for name, obj in after.items():
            expected = 2 if name.startswith('键_0_1_') else 1
            self.assertAlmostEqual(obj.matrix.v1.GetLength(), expected)
            self.assertAlmostEqual(obj.matrix.v3.GetLength(), expected)
        for name in after:
            if name.endswith('_A'):
                mate = name[:-2] + '_B'
                self.assertAlmostEqual(
                    after[name].matrix.v2.GetLength() + after[mate].matrix.v2.GetLength(),
                    before[name].matrix.v2.GetLength() + before[mate].matrix.v2.GetLength())
        self.assertEqual(len(self.builder._material_specs(record, style)),
                         len(self.builder._material_specs(record, normalized_style())))

    def test_fill_keeps_absolute_local_radius_semantics(self):
        record = self.molecule()
        style = normalized_style({'representation': 'space_fill', 'atom_radius': 1.0,
                                  'atom_radius_overrides': {'0': .6}})
        mats = {('atom', 'C'): object(), ('atom', 'O'): object(),
                ('bond', 'C'): object(), ('bond', 'O'): object()}
        root = self.builder._make_hierarchy(record, style, mats)
        atoms_group, bonds_group, templates = root.children
        atom = next(obj for obj in atoms_group.children if obj.name == '原子_C_0')
        carbon = next(obj for obj in templates.children if obj.name == '球母体_C')
        self.assertAlmostEqual(atom.scale.x, .6)
        self.assertAlmostEqual(carbon.values[self.c4d.PRIM_SPHERE_RAD] * atom.scale.x,
                               .6 * 50 * 1.7)
        self.assertEqual(bonds_group.values[self.c4d.ID_BASEOBJECT_VISIBILITY_EDITOR],
                         self.c4d.MODE_OFF)
        self.assertEqual(style['atom_radius_overrides'], {'0': .6})


if __name__ == '__main__':
    unittest.main()
