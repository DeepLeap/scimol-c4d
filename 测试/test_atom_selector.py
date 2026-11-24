"""Mouse trajectory regression tests with SDK input stand-ins, not host proof."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Widget:
    def __init__(self):
        pass


class MouseMessage(dict):
    def GetInt32(self, key):
        return self.get(key, 0)


class InputTests(unittest.TestCase):
    def setUp(self):
        sdk = types.ModuleType('c4d')
        sdk.gui = types.SimpleNamespace(GeUserArea=Widget, GeDialog=Widget, SubDialog=Widget)
        names = ('BFM_INPUT_DEVICE', 'BFM_INPUT_MOUSE', 'BFM_INPUT_CHANNEL',
                 'BFM_INPUT_MOUSELEFT', 'BFM_INPUT_MOUSERIGHT', 'BFM_INPUT_VALUE',
                 'BFM_INPUT_X', 'BFM_INPUT_Y', 'MOUSEDRAGFLAGS_DONTHIDEMOUSE',
                 'MOUSEDRAGRESULT_CONTINUE', 'MOUSEDRAGRESULT_FINISHED', 'MOUSEDRAGRESULT_ESCAPE')
        for index, name in enumerate(names, 1): setattr(sdk, name, index)
        self.sdk = sdk
        replacement = patch.dict(sys.modules, {'c4d': sdk})
        replacement.start()
        self.addCleanup(replacement.stop)
        spec = importlib.util.spec_from_file_location('scimol_c4d._atom_input_test', ROOT / 'scimol_c4d/atom_selector.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def area(self, packets, end=None):
        owner = types.SimpleNamespace(boxes=[], editing=True, show_groups=False,
                                      groups={}, selected_ids=set(), selected_bonds=set(),
                                      background_white=0)
        owner._select_box = lambda *box: owner.boxes.append(box)
        area = self.module._AtomImage(owner)
        area.Global2Local = lambda: {'x': -100, 'y': -70}
        area.GetWidth = lambda: 360
        area.GetHeight = lambda: 280
        area.MouseDragStart = lambda *args: setattr(area, 'started', args)
        stream = iter(packets)
        area.MouseDrag = lambda: next(stream)
        area.ended_count = 0

        def finish():
            area.ended_count += 1
            return self.sdk.MOUSEDRAGRESULT_FINISHED if end is None else end

        area.MouseDragEnd = finish
        area.frames = []
        area.Redraw = lambda: area.frames.append(area.drag_box)
        msg = MouseMessage({self.sdk.BFM_INPUT_DEVICE:self.sdk.BFM_INPUT_MOUSE,
                            self.sdk.BFM_INPUT_CHANNEL:self.sdk.BFM_INPUT_MOUSELEFT,
                            self.sdk.BFM_INPUT_VALUE:1, self.sdk.BFM_INPUT_X:110,
                            self.sdk.BFM_INPUT_Y:90})
        return area, owner, msg

    def test_drag_follows_all_four_cursor_directions_in_local_space(self):
        for cursor_dx, cursor_dy in ((-50, -40), (-50, 40), (50, -40), (50, 40)):
            with self.subTest(cursor_dx=cursor_dx, cursor_dy=cursor_dy):
                area, owner, msg = self.area([
                    # Native C4D uses previous-current, corroborated by the
                    # user's real right/down drag and Maxon's marquee example.
                    (self.sdk.MOUSEDRAGRESULT_CONTINUE, -cursor_dx, -cursor_dy, None),
                    (self.sdk.MOUSEDRAGRESULT_FINISHED, 0, 0, None)])
                self.assertTrue(area.InputEvent(msg))
                self.assertEqual(area.started[:3], (self.sdk.BFM_INPUT_MOUSELEFT, 10.0, 20.0))
                self.assertEqual(owner.boxes, [(10, 20, 10+cursor_dx, 20+cursor_dy)])
                self.assertIn((10, 20, 10+cursor_dx, 20+cursor_dy), area.frames)
                self.assertEqual(area.last_drag['end'], [10+cursor_dx, 20+cursor_dy])
                self.assertEqual(area.ended_count, 1)
                self.assertIsNone(area.drag_box)

    def test_escape_cleans_drag_without_changing_selection(self):
        area, owner, msg = self.area([
            (self.sdk.MOUSEDRAGRESULT_CONTINUE, -25, -15, None),
            (self.sdk.MOUSEDRAGRESULT_ESCAPE, 0, 0, None)], self.sdk.MOUSEDRAGRESULT_ESCAPE)
        area.InputEvent(msg)
        self.assertEqual(owner.boxes, [])
        self.assertEqual(area.ended_count, 1)
        self.assertIsNone(area.drag_box)

    def test_click_keeps_the_original_local_hotspot(self):
        area, owner, msg = self.area([(self.sdk.MOUSEDRAGRESULT_FINISHED, 0, 0, None)])
        area.InputEvent(msg)
        self.assertEqual(owner.boxes, [(10, 20, 10.0, 20.0)])

    def test_drag_accumulates_packets_in_local_space(self):
        area, owner, msg = self.area([
            (self.sdk.MOUSEDRAGRESULT_CONTINUE, -8, -5, None),
            (self.sdk.MOUSEDRAGRESULT_CONTINUE, -7, 2, None),
            (self.sdk.MOUSEDRAGRESULT_FINISHED, 0, 0, None)])
        area.InputEvent(msg)
        self.assertEqual(area.frames[:2], [(10, 20, 18, 25), (10, 20, 25, 23)])
        self.assertEqual(owner.boxes, [(10, 20, 25, 23)])

    def test_preview_ignores_mouse_and_uses_available_area(self):
        area, owner, msg = self.area([])
        owner.editing = False
        area.GetWidth = lambda: 720
        area.GetHeight = lambda: 560
        self.assertEqual(area._image_box(), (0, 0, 720, 560))
        self.assertFalse(area.InputEvent(msg))
        self.assertEqual(owner.boxes, [])

    def test_set_editing_hides_only_editor_controls(self):
        panel = self.module.AtomSelectionPanel(lambda *_args: None,
                                               lambda: None)
        hidden = []
        panel.HideElement = lambda identifier, value: hidden.append((identifier, value))
        panel._image.Redraw = lambda: None
        panel.LayoutChanged = lambda _identifier: None
        panel._layout_ready = True
        panel.set_editing(False)
        panel.set_editing(True)
        self.assertEqual(hidden, [(self.module.EDIT_CONTROLS, True),
                                  (self.module.EDIT_CONTROLS, False)])

    def test_drawing_clears_buffer_and_uses_subtle_relation_fill(self):
        area, owner, _msg = self.area([])
        owner.show_groups = True
        owner.groups = {'1': {'atom_ids': [1, 2], 'color': [0.9, 0.2, 0.2]}}
        area.positions = {1: (50, 60), 2: (100, 80)}
        area.bitmap = types.SimpleNamespace(GetBw=lambda: 360, GetBh=lambda: 280)
        self.sdk.Vector = lambda *values: values
        self.sdk.BMP_NORMALSCALED = 123
        self.sdk.BMP_ALLOWALPHA = 256
        self.sdk.COLOR_BG = 456
        area.GetColorRGB = lambda _id: {'r': 40, 'g': 45, 'b': 50}
        calls = []
        for method in ('OffScreenOn', 'SetClippingRegion', 'DrawSetOpacity', 'DrawSetPen',
                       'DrawRectangle', 'DrawBitmap', 'DrawRoundedRectangle',
                       'DrawEllipseFill', 'DrawEllipseLine', 'DrawFrame', 'DrawText',
                       'DrawLine'):
            setattr(area, method, lambda *args, _name=method: calls.append((_name, args)))
        self.assertTrue(area.DrawMsg(0, 0, 360, 280, None))
        names = [name for name, _args in calls]
        self.assertEqual(names[:5], ['OffScreenOn', 'SetClippingRegion', 'DrawSetOpacity',
                                     'DrawSetPen', 'DrawRectangle'])
        self.assertLess(names.index('DrawBitmap'), names.index('DrawRoundedRectangle'))
        self.assertIn(('DrawSetOpacity', (0.13,)), calls)
        self.assertIn(('DrawSetOpacity', (1.0,)), calls)
        self.assertNotIn('DrawText', names)
        self.assertNotIn('DrawEllipseLine', names)

    def test_transparent_ink_blends_over_live_native_background(self):
        area, owner, _msg = self.area([])
        owner.show_groups = False
        owner.background_white = 50
        area.bitmap = None
        area.light_bitmap = types.SimpleNamespace(GetBw=lambda: 360, GetBh=lambda: 280)
        area.dark_bitmap = types.SimpleNamespace(GetBw=lambda: 360, GetBh=lambda: 280)
        self.sdk.Vector = lambda *values: values
        self.sdk.BMP_NORMALSCALED = 123
        self.sdk.BMP_ALLOWALPHA = 256
        self.sdk.COLOR_BG = 456
        area.GetColorRGB = lambda _id: {'r': 40, 'g': 45, 'b': 50}
        calls = []
        for method in ('OffScreenOn', 'SetClippingRegion', 'DrawSetOpacity', 'DrawSetPen',
                       'DrawRectangle', 'DrawBitmap'):
            setattr(area, method, lambda *args, _name=method: calls.append((_name, args)))
        area.DrawMsg(0, 0, 360, 280, None)
        drawn = [args for name, args in calls if name == 'DrawBitmap']
        self.assertEqual(len(drawn), 1)
        self.assertIs(drawn[0][0], area.dark_bitmap)
        self.assertTrue(all(args[-1] == 123 | 256 for args in drawn))
        owner.background_white = 0
        calls.clear()
        area.DrawMsg(0, 0, 360, 280, None)
        drawn = [args for name, args in calls if name == 'DrawBitmap']
        self.assertIs(drawn[0][0], area.light_bitmap)
        native = self.module._background_color({'r': 40, 'g': 45, 'b': 50}, 0)
        white = self.module._background_color({'r': 40, 'g': 45, 'b': 50}, 100)
        self.assertEqual(native, (40 / 255, 45 / 255, 50 / 255))
        self.assertEqual(white, (1.0, 1.0, 1.0))

    def test_background_controls_do_not_touch_selection_or_plane_groups(self):
        panel = self.module.AtomSelectionPanel(lambda *_args: None, lambda: None)
        panel.selected_ids = {7}
        panel.groups = {'1': {'atom_ids': [7], 'color': [1, 0, 0]}}
        panel.GetInt32 = lambda _id: 35
        changed = []
        panel.SetInt32 = lambda *args, **kwargs: changed.append((args, kwargs))
        panel._image.Redraw = lambda: changed.append(('redraw',))
        panel.Command(self.module.BACKGROUND_SLIDER, None)
        self.assertEqual(panel.background_white, 35)
        self.assertEqual(panel.selected_ids, {7})
        self.assertEqual(panel.groups['1']['atom_ids'], [7])
        self.assertEqual(len(changed), 3)

    def test_editor_uses_the_same_scaled_coordinates_as_the_large_diagram(self):
        area, _owner, _msg = self.area([])
        area.GetWidth = lambda: 720
        area.GetHeight = lambda: 560
        self.assertEqual(area._image_box(), (0, 0, 720, 560))
        area.positions = {7:(100,100)}
        self.assertEqual(area._hit(200,200), 7)

    def panel_with_visible_bond(self):
        events = []
        panel = self.module.AtomSelectionPanel(lambda *_args: None, lambda: None,
                                                on_local_appearance=lambda *args: events.append(args))
        panel._image.GetWidth = lambda: 360
        panel._image.GetHeight = lambda: 280
        panel._image.positions = {1: (80, 100), 2: (160, 100), 3: (240, 100)}
        panel._image.bonds = {'1:2': (1, 2), '2:3': (2, 3)}
        panel._layout_ready = False
        return panel, events

    def test_bond_hit_uses_canvas_pixels_and_avoids_atom_hotspots(self):
        panel, _events = self.panel_with_visible_bond()
        area = panel._image
        self.assertEqual(area._hit_bond(120, 105), '1:2')
        self.assertIsNone(area._hit_bond(87, 100))
        self.assertIsNone(area._hit_bond(120, 109))
        area.GetWidth = lambda: 720
        area.GetHeight = lambda: 560
        self.assertEqual(area._hit_bond(240, 205), '1:2')

    def test_click_replaces_selection_and_empty_click_clears(self):
        panel, _events = self.panel_with_visible_bond()
        panel._select_box(120, 100, 120, 100)
        self.assertEqual(panel.selected_bonds, {'1:2'})
        panel._select_box(160, 100, 160, 100)
        self.assertEqual(panel.selected_ids, {2})
        self.assertFalse(panel.selected_bonds)
        panel._select_box(30, 30, 30, 30)
        self.assertFalse(panel.selected_ids)

    def test_frame_and_select_all_include_only_visible_bonds(self):
        panel, _events = self.panel_with_visible_bond()
        panel._select_box(70, 90, 170, 110)
        self.assertEqual(panel.selected_ids, {1, 2})
        self.assertEqual(panel.selected_bonds, {'1:2'})
        panel.Command(self.module.SELECT_ALL, None)
        self.assertEqual(panel.selected_bonds, {'1:2', '2:3'})
        panel.Command(self.module.CLEAR, None)
        self.assertFalse(panel.selected_ids)
        self.assertFalse(panel.selected_bonds)

    def test_local_commands_ignore_empty_selection_and_translate_display_values(self):
        panel, events = self.panel_with_visible_bond()
        panel.GetFloat = lambda _identifier: 2
        panel.Command(self.module.LOCAL_ATOM_RADIUS, None)
        panel.Command(self.module.LOCAL_BOND_RADIUS, None)
        panel.Command(self.module.LOCAL_RESET, None)
        self.assertEqual(events, [])
        panel.selected_ids = {1, 2}
        panel.selected_bonds = {'1:2'}
        panel.Command(self.module.LOCAL_ATOM_RADIUS, None)
        panel.Command(self.module.LOCAL_BOND_RADIUS, None)
        panel.Command(self.module.LOCAL_RESET, None)
        self.assertAlmostEqual(events[0][2], self.module.to_physical('atom_radius', 2))
        self.assertAlmostEqual(events[1][2], .08)
        self.assertEqual(events[0][:2], ('atoms', [1, 2]))
        self.assertEqual(events[1][:2], ('bonds', ['1:2']))
        self.assertEqual(events[2], ('reset', {'atoms': [1, 2], 'bonds': ['1:2']}, None))

    def test_style_sync_preserves_selection_and_reports_mixed_values(self):
        panel, _events = self.panel_with_visible_bond()
        panel.selected_ids = {1, 2}
        panel.selected_bonds = {'1:2'}
        panel._layout_ready = True
        numbers, enabled, labels = {}, {}, {}
        panel.SetFloat = lambda identifier, value, **_kwargs: numbers.__setitem__(identifier, value)
        panel.Enable = lambda identifier, value: enabled.__setitem__(identifier, value)
        panel.SetString = lambda identifier, value: labels.__setitem__(identifier, value)
        panel.set_appearance({'atom_radius': .3, 'bond_radius': .08,
                              'atom_radius_overrides': {'1': .4},
                              'bond_radius_overrides': {'1:2': .12}})
        self.assertEqual(panel.selected_ids, {1, 2})
        self.assertEqual(panel.selected_bonds, {'1:2'})
        self.assertAlmostEqual(numbers[self.module.LOCAL_ATOM_RADIUS],
                               round(self.module.to_display('atom_radius', .4), 1))
        self.assertAlmostEqual(numbers[self.module.LOCAL_BOND_RADIUS],
                               round(self.module.to_display('bond_radius', .12), 1))
        self.assertIn('不同', labels[self.module.LOCAL_ATOM_NOTE])
        self.assertTrue(enabled[self.module.LOCAL_RESET])

    def test_plane_group_change_calls_scene_immediately(self):
        updated = []
        panel, _events = self.panel_with_visible_bond()
        panel.on_apply_groups = lambda groups: updated.append(groups) or True
        panel._record = {'atoms': [{'id': 1, 'element': 'C', 'x': 0, 'y': 0, 'z': 0},
                                   {'id': 2, 'element': 'C', 'x': 1, 'y': 0, 'z': 0}],
                         'bonds': []}
        panel.selected_ids = {1, 2}
        panel._assign_group()
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['1']['atom_ids'], [1, 2])
        self.assertFalse(panel.groups_dirty)
        panel.selected_ids = {2}
        panel._remove_from_groups()
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[1]['1']['atom_ids'], [1])

    def test_orientation_and_center_are_independent_from_flatten(self):
        orientations, flatten = [], []
        panel, _events = self.panel_with_visible_bond()
        panel.on_orientation = lambda direction, ids: orientations.append((direction, ids)) or True
        panel.on_flatten = lambda ids, plane: flatten.append((ids, plane)) or True
        panel.GetInt32 = lambda _id: 2
        panel.Command(self.module.PLANE, None)
        self.assertEqual(orientations, [('xy', [])])
        panel.selected_ids = {2}
        panel.Command(self.module.SET_CENTER, None)
        self.assertEqual(orientations[-1], ('xy', [2]))
        panel.Command(self.module.ALL_FLATTEN, None)
        self.assertEqual(flatten, [(None, 'auto')])
        panel.Command(self.module.RESET_CENTER, None)
        self.assertEqual(orientations[-1], ('xy', []))

    def test_ring_center_prefers_benzene_and_can_choose_other_rings(self):
        panel, _events = self.panel_with_visible_bond()
        panel._image.positions = {index: (index * 10, 20) for index in range(9)}
        panel._record = {'atoms': [{'id': i, 'element': 'C'} for i in range(9)],
                         'bonds': [{'a': i, 'b': (i+1) % 3, 'aromatic': True} for i in range(3)] +
                                  [{'a': i, 'b': 3+(i-3+1) % 6, 'aromatic': True} for i in range(3,9)]}
        panel.selected_ids = {1}
        self.assertEqual(panel._aromatic_ring_ids(), [0, 1, 2])
        panel.selected_ids.clear()
        self.assertEqual(panel._aromatic_ring_ids(), [3, 4, 5, 6, 7, 8])
        panel.ring_options = self.module.ring_center_options(panel._record)
        orientations = []
        panel.on_orientation = lambda direction, ids: orientations.append((direction, ids)) or True
        panel.GetInt32 = lambda _id: 2
        panel.Command(self.module.RING_CENTER, None)
        self.assertEqual(orientations[-1][1], [0, 1, 2])
        panel.GetInt32 = lambda _id: 1
        panel.Command(self.module.RING_CENTER, None)
        self.assertEqual(orientations[-1][1], [3, 4, 5, 6, 7, 8])
        panel.GetInt32 = lambda _id: 0
        panel.Command(self.module.RING_CENTER, None)
        self.assertEqual(orientations[-1][1], [])

    def test_closing_details_notifies_the_main_panel(self):
        events = []
        panel = self.module.AtomSelectionPanel(lambda *_args: None, lambda: None,
                                               on_close=lambda: events.append('closed'))
        self.assertFalse(panel.AskClose())
        self.assertEqual(events, ['closed'])


if __name__ == '__main__':
    unittest.main()
