"""Whole-molecule orientation and continuous appearance contracts."""

import copy
import importlib.util
import math
import unittest
from pathlib import Path

from scimol_c4d.display_geometry import orient_display_positions
from scimol_c4d.records import normalized_style


class OrientationPresetTests(unittest.TestCase):
    @staticmethod
    def molecule():
        # A tilted hexagon plus an oxygen substituent and one spatial H.
        positions = {}
        for atom_id in range(6):
            theta = atom_id * math.pi / 3
            positions[atom_id] = [1 + math.cos(theta), 2 + math.sin(theta),
                                  3 + .5 * math.sin(theta)]
        positions[6] = [2.8, 2.0, 3.4]
        positions[7] = [3.2, 2.4, 4.0]
        atoms = [{'id': i, 'element': 'H' if i == 7 else 'O' if i == 6 else 'C'}
                 for i in range(8)]
        bonds = [{'a': i, 'b': (i + 1) % 6} for i in range(6)]
        bonds += [{'a': 0, 'b': 6}, {'a': 6, 'b': 7}]
        return {'atoms': atoms, 'bonds': bonds}, positions

    def test_axis_presets_are_rigid_and_align_ring(self):
        record, positions = self.molecule()
        original = copy.deepcopy(positions)
        for orientation, flat_axis in [('auto', 2), ('xy', 2), ('xz', 1), ('yz', 0)]:
            with self.subTest(orientation=orientation):
                result = orient_display_positions(record, positions, orientation)
                for bond in record['bonds']:
                    a, b = bond['a'], bond['b']
                    self.assertAlmostEqual(math.dist(positions[a], positions[b]),
                                           math.dist(result[a], result[b]), places=8)
                self.assertLess(max(abs(result[i][flat_axis]) for i in range(6)), 1e-8)
                ring_center = [sum(result[i][axis] for i in range(6)) / 6
                               for axis in range(3)]
                self.assertLess(math.dist(ring_center, [0, 0, 0]), 1e-8)
        self.assertEqual(positions, original)

    def test_selected_center_and_original_preserves_rotation(self):
        record, positions = self.molecule()
        for orientation in ('original', 'xy'):
            result = orient_display_positions(record, positions, orientation, [6])
            self.assertEqual(result[6], [0.0, 0.0, 0.0])
        original = orient_display_positions(record, positions, 'original')
        delta = [original[0][i] - original[1][i] for i in range(3)]
        self.assertEqual(delta, [positions[0][i] - positions[1][i] for i in range(3)])

    def test_chosen_second_ring_controls_alignment(self):
        record, positions = self.molecule()
        record['atoms'] = record['atoms'][:6]
        record['bonds'] = record['bonds'][:6]
        positions = {i: positions[i] for i in range(6)}
        for i in range(6):
            theta = i*math.pi/3
            atom_id = i+6
            positions[atom_id] = [5+math.cos(theta), 1., math.sin(theta)]
            record['atoms'].append({'id':atom_id,'element':'C'})
            record['bonds'].append({'a':atom_id,'b':(i+1)%6+6,'aromatic':True})
        for bond in record['bonds']: bond['aromatic']=True
        record['bonds'].append({'a':0,'b':6})
        result=orient_display_positions(record,positions,'xy',list(range(6,12)))
        self.assertLess(max(abs(result[i][2]) for i in range(6,12)),1e-8)
        self.assertGreater(max(abs(result[i][2]) for i in range(6)),.5)
        for a in positions:
            for b in positions:
                self.assertAlmostEqual(math.dist(positions[a],positions[b]),
                                       math.dist(result[a],result[b]),places=8)

    def test_auto_prefers_aromatic_six_ring_over_larger_aromatic_cycle(self):
        record = {'atoms': [], 'bonds': []}
        positions = {}
        for size, offset in ((6, 0), (8, 6)):
            for index in range(size):
                atom_id = offset + index
                theta = 2 * math.pi * index / size
                positions[atom_id] = ([math.cos(theta), math.sin(theta), 0.]
                                      if size == 6 else
                                      [4., math.cos(theta), math.sin(theta)])
                record['atoms'].append({'id': atom_id, 'element': 'C'})
                record['bonds'].append({'a': atom_id, 'b': offset + (index + 1) % size,
                                        'aromatic': True})
        record['bonds'].append({'a': 0, 'b': 6})
        result = orient_display_positions(record, positions, 'auto')
        self.assertLess(max(abs(result[i][2]) for i in range(6)), 1e-8)
        self.assertGreater(max(abs(result[i][2]) for i in range(6, 14)), .5)
        for a in positions:
            for b in positions:
                self.assertAlmostEqual(math.dist(positions[a], positions[b]),
                                       math.dist(result[a], result[b]), places=8)

    def test_auto_aligns_acyclic_center_to_real_bond(self):
        positions = {0: [-3., -3., 0.], 1: [-1., -1., 0.],
                     2: [1., 1., 0.], 3: [3., 3., 0.],
                     4: [-3.7, -2.3, 0.]}
        record = {'atoms': [{'id': i, 'element': 'C'} for i in positions],
                  'bonds': [{'a': i, 'b': i+1} for i in range(3)] +
                           [{'a': 0, 'b': 4}]}
        result = orient_display_positions(record, positions, 'auto')
        spread_x = sum(result[i][0] ** 2 for i in positions)
        spread_y = sum(result[i][1] ** 2 for i in positions)
        self.assertGreater(spread_x, spread_y * 10)
        self.assertEqual(result[1], [0.0, 0.0, 0.0])
        self.assertGreater(result[0][0], 0)
        self.assertAlmostEqual(result[0][1], 0.0, places=8)
        self.assertAlmostEqual(result[0][2], 0.0, places=8)
        for a in positions:
            for b in positions:
                self.assertAlmostEqual(math.dist(positions[a], positions[b]),
                                       math.dist(result[a], result[b]), places=8)

    def test_new_style_defaults_and_rejects_invalid_center_or_caps(self):
        defaults = normalized_style()
        self.assertTrue(defaults['bond_caps'])
        self.assertEqual(defaults['orientation'], 'auto')
        self.assertEqual(defaults['center_atom_ids'], [])
        new = normalized_style({'representation': 'continuous', 'center_atom_ids': [6, 0, 6],
                                'bond_caps': False, 'orientation': 'xz'})
        self.assertEqual(new['center_atom_ids'], [0, 6])
        for style in ({'center_atom_ids': [True]}, {'bond_caps': 0},
                      {'orientation': 'side'}, {'center_atom_ids': [300]}):
            with self.subTest(style=style), self.assertRaises(ValueError):
                normalized_style(style)
        record, positions = self.molecule()
        with self.assertRaises(ValueError):
            orient_display_positions(record, positions, 'xy', [99])

    def test_builder_continuous_endpoints_and_cap_setting(self):
        # Existing tiny C4D stubs exercise actual builder math without a host.
        spec = importlib.util.spec_from_file_location(
            '_orientation_c4d_stub', Path(__file__).with_name('test_local_appearance.py'))
        mock_c4d = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mock_c4d)
        harness = mock_c4d.LocalAppearanceTests
        harness.setUpClass()
        try:
            builder, c4d = harness.builder, harness.c4d
            record = harness.molecule()
            mats = {('atom', 'C'): object(), ('atom', 'O'): object(),
                    ('bond', 'C'): object(), ('bond', 'O'): object()}
            for radius, factor in ((.30, 1.0), (.65, 1.35), (1.0, 1.7), (1.4, 1.7)):
                with self.subTest(radius=radius):
                    style = normalized_style({'representation': 'continuous',
                                              'atom_radius': radius, 'bond_caps': False})
                    root = builder._make_hierarchy(record, style, mats)
                    self.assertTrue(root.children[1].children)
                    prototypes = root.children[2].children
                    carbon = next(obj for obj in prototypes if obj.name == '球母体_C')
                    self.assertAlmostEqual(carbon.values[c4d.PRIM_SPHERE_RAD],
                                           radius * style['scale'] * factor)
                    caps = [obj.values[c4d.PRIM_CYLINDER_CAPS] for obj in prototypes
                            if obj.kind == c4d.Ocylinder]
                    self.assertEqual(caps, [False, False])
            legacy = normalized_style({'representation': 'space_fill', 'atom_radius': 1.0})
            root = builder._make_hierarchy(record, legacy, mats)
            self.assertEqual(root.children[1].values[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR],
                             c4d.MODE_OFF)
        finally:
            harness.tearDownClass()


if __name__ == '__main__':
    unittest.main()
