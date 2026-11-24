"""Native reset icon and independent detail-slider reset contracts."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from PIL import Image
from scimol_c4d.appearance_scale import to_display


ROOT = Path(__file__).resolve().parents[1]


class SliderResetTests(unittest.TestCase):
    def setUp(self):
        class Widget:
            pass

        sdk = types.ModuleType("c4d")
        sdk.gui = types.SimpleNamespace(GeUserArea=Widget, GeDialog=Widget,
                                        SubDialog=Widget)
        replacement = patch.dict(sys.modules, {"c4d": sdk})
        replacement.start()
        self.addCleanup(replacement.stop)
        spec = importlib.util.spec_from_file_location(
            "scimol_c4d._slider_reset_test", ROOT / "scimol_c4d" / "atom_selector.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def appearance_panel(self, style):
        panel = self.module.AtomSelectionPanel(
            lambda *_args: None, lambda: None,
            on_local_appearance=lambda *_args: True)
        panel._record = {"atoms": [{"id": 0, "element": "C"},
                                   {"id": 1, "element": "O"}]}
        panel._layout_ready = True
        panel.values = {}
        panel.SetFloat = lambda identifier, value, **_kwargs: panel.values.__setitem__(identifier, value)
        panel.SetString = lambda identifier, value: panel.values.__setitem__(identifier, value)
        panel.Enable = lambda *_args: None
        panel.set_appearance(style)
        return panel

    def test_local_atom_reset_displays_inherited_element_scale(self):
        panel = self.appearance_panel({"atom_radius": .3,
            "element_scales": {"C": 2.}, "atom_radius_overrides": {"0": .45}})
        panel.selected_ids = {0}
        panel._refresh_appearance()
        self.assertEqual(panel.values[self.module.LOCAL_ATOM_RADIUS],
                         round(to_display("atom_radius", .45), 1))
        panel.Command(self.module.LOCAL_ATOM_RESET, None)
        self.assertEqual(panel._appearance["atom_radius_overrides"], {})
        self.assertEqual(panel.values[self.module.LOCAL_ATOM_RADIUS],
                         round(to_display("atom_radius", .6), 1))

    def test_mixed_element_scales_show_mixed_selection(self):
        panel = self.appearance_panel({"atom_radius": .3, "element_scales": {"C": 2.}})
        panel.selected_ids = {0, 1}
        panel._refresh_appearance()
        self.assertEqual(panel.values[self.module.LOCAL_ATOM_NOTE], "所选值不同；编辑后统一")
        self.assertEqual(panel.values[self.module.LOCAL_ATOM_RADIUS],
                         round(to_display("atom_radius", .6), 1))

    def test_legacy_element_radius_and_bond_radius_keep_precedence(self):
        panel = self.appearance_panel({"atom_radius": .3, "bond_radius": .08,
            "element_scales": {"C": 2.}, "element_radius_overrides": {"C": .7},
            "bond_radius_overrides": {"0:1": .2}})
        panel.selected_ids = {0}
        panel.selected_bonds = {"0:1"}
        panel._refresh_appearance()
        self.assertEqual(panel.values[self.module.LOCAL_ATOM_RADIUS],
                         round(to_display("atom_radius", .7), 1))
        self.assertEqual(panel.values[self.module.LOCAL_BOND_RADIUS],
                         round(to_display("bond_radius", .2), 1))
        panel.Command(self.module.LOCAL_BOND_RESET, None)
        self.assertEqual(panel.values[self.module.LOCAL_BOND_RADIUS],
                         round(to_display("bond_radius", .08), 1))

    def test_detail_resets_only_selected_kind(self):
        calls = []
        panel = self.module.AtomSelectionPanel(
            lambda *_args: None, lambda: None,
            on_local_appearance=lambda *args: calls.append(args) or True)
        panel.selected_ids = {1, 2}
        panel.selected_bonds = {"1:2"}
        panel._layout_ready = False
        panel._appearance["atom_radius_overrides"] = {"1": .4}
        panel._appearance["bond_radius_overrides"] = {"1:2": .2}
        panel.Command(self.module.LOCAL_ATOM_RESET, None)
        self.assertEqual(calls[-1], ("reset", {"atoms": [1, 2], "bonds": []}, None))
        self.assertEqual(panel._appearance["atom_radius_overrides"], {})
        self.assertEqual(panel._appearance["bond_radius_overrides"], {"1:2": .2})
        panel.Command(self.module.LOCAL_BOND_RESET, None)
        self.assertEqual(calls[-1], ("reset", {"atoms": [], "bonds": ["1:2"]}, None))
        self.assertEqual(panel._appearance["bond_radius_overrides"], {})
        panel.selected_ids.clear()
        panel.Command(self.module.LOCAL_ATOM_RESET, None)
        self.assertEqual(len(calls), 2)

    def test_background_reset_restores_zero_even_in_preview(self):
        panel = self.module.AtomSelectionPanel(lambda *_args: None, lambda: None)
        panel.background_white = 63
        panel.editing = False
        values = {}
        panel.SetInt32 = lambda identifier, value, **_kwargs: values.__setitem__(identifier, value)
        redraws = []
        panel._image.Redraw = lambda: redraws.append(True)
        panel.Command(self.module.BACKGROUND_RESET, None)
        self.assertEqual(panel.background_white, 0)
        self.assertEqual(values, {self.module.BACKGROUND_WHITE: 0,
                                  self.module.BACKGROUND_SLIDER: 0})
        self.assertEqual(redraws, [True])

    def test_reset_asset_is_transparent_sixteen_pixel_png(self):
        path = ROOT / "assets" / "reset.png"
        with Image.open(path) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (16, 16))
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertGreater(image.getchannel("A").getextrema()[1], 0)


if __name__ == "__main__":
    unittest.main()
