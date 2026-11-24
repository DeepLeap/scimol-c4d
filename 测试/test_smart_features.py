"""Tests for persistent worker reuse, smart search, smart UI controls, and 2D multi-select."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scimol_c4d import backend as backend_mod, chemistry_worker, search_index
from scimol_c4d.library import Library
from scimol_c4d.records import normalized_style
from 测试.test_browser_states import BaseContainer, DialogAPI, Editor, Root
from 测试.test_ui_logic import FakeBackend, FakeDocument


class BackendPersistentTests(unittest.TestCase):
    def test_persistent_worker_reuses_same_pid_and_closes_cleanly(self):
        backend = backend_mod.Backend()
        self.addCleanup(backend.close)
        backend.submit({"action": "resolve", "kind": "smiles", "text": "CCO"}, "first")
        _, _, r1, _ = backend.results.get(timeout=20)
        self.assertTrue(r1["ok"])
        first_proc = backend._daemon.process
        first_pid = first_proc.pid

        backend.submit({"action": "resolve", "kind": "smiles", "text": "c1ccccc1"}, "second")
        _, _, r2, _ = backend.results.get(timeout=20)
        self.assertTrue(r2["ok"])
        self.assertIsNotNone(backend._daemon)
        self.assertEqual(backend._daemon.process.pid, first_pid)

        backend.close()
        self.assertIsNone(backend._daemon)
        self.assertIsNotNone(first_proc.poll())

    def test_cancel_in_flight_request_recovers_for_next_request(self):
        backend = backend_mod.Backend()
        self.addCleanup(backend.close)
        backend.submit({"action": "builtin"}, "old")
        token = backend.submit({"action": "resolve", "kind": "name", "text": "四氢呋喃"}, "new")
        res_token, context, result, _ = backend.results.get(timeout=20)
        self.assertEqual(res_token, token)
        self.assertEqual(context, "new")
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"][0]["name"], "四氢呋喃")

    def test_log_rotation_truncates_oversized_log(self):
        with tempfile.TemporaryDirectory() as folder:
            temp_data = Path(folder)
            log_file = temp_data / "运行日志.txt"
            log_file.write_bytes(b"old log line\n" * 25000)  # > 256 KB
            self.assertGreater(log_file.stat().st_size, backend_mod._LOG_MAX_BYTES)
            with patch.object(backend_mod, "DATA", temp_data):
                backend_mod.Backend._log("marker_after_rotation")
            self.assertLess(log_file.stat().st_size, backend_mod._LOG_MAX_BYTES)
            self.assertIn("marker_after_rotation", log_file.read_text(encoding="utf-8"))


class SmartSearchTests(unittest.TestCase):
    def test_unicode_subscript_and_prefix_normalization(self):
        self.assertEqual(search_index.normalize_query_text("  SMILES: CCO  "), "CCO")
        self.assertEqual(search_index.normalize_query_text("分子式：C₆H₁₂O₆"), "C6H12O6")
        self.assertEqual(search_index.normalize_query_text("CO"), "CO")
        self.assertEqual(search_index.normalize_query_text("Co"), "Co")

    def test_formula_validation_rejects_abbreviations_and_bare_words(self):
        for bad in ("THF", "DMF", "DMSO", "DCM", "EtOH", "MeOH", "EDTA", "ATP", "In", "No", "As"):
            with self.subTest(bad=bad):
                self.assertFalse(search_index.is_valid_formula(bad))
        for good in ("H2O", "C2H6O", "C6H12O6", "C₆H₁₂O₆", "NaCl", "O2", "CO2"):
            with self.subTest(good=good):
                self.assertTrue(search_index.is_valid_formula(good))

    def test_local_library_abbreviations_never_hijack_short_smiles(self):
        self.assertEqual(search_index.rank_local_names("THF"), ["四氢呋喃"])
        self.assertEqual(search_index.rank_local_names("dmso"), ["二甲基亚砜"])
        for smiles in ("CO", "Co", "CCO", "C", "O", "N", "CC"):
            with self.subTest(smiles=smiles):
                self.assertEqual(search_index.rank_local_names(smiles), [])
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            with patch.object(chemistry_worker, "_network", side_effect=AssertionError("network called")):
                thf = chemistry_worker.handle({"action": "resolve", "kind": "auto", "text": "THF", "cache_dir": str(cache)})
                self.assertEqual(thf["records"][0]["name"], "四氢呋喃")
                co = chemistry_worker.handle({"action": "resolve", "kind": "auto", "text": "CO", "cache_dir": str(cache)})
                self.assertEqual(co["records"][0]["formula"], "CH4O")
                self.assertEqual(co["records"][0]["source"]["kind"], "smiles")

    def test_smart_input_hint_distinguishes_modes(self):
        self.assertIn("四氢呋喃", search_index.smart_input_hint("THF"))
        self.assertIn("分子式 C6H12O6", search_index.smart_input_hint("C₆H₁₂O₆"))
        self.assertIn("SMILES", search_index.smart_input_hint("CCO"))
        self.assertIn("未收录", search_index.smart_input_hint("未知分子XYZ"))


class SmartBrowserUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cache = str(Path(cls.fixture.name) / "cache")
        cls.ethanol = chemistry_worker.handle({"action": "generate", "record":
            chemistry_worker.handle({"action": "resolve", "kind": "smiles", "text": "CCO", "cache_dir": cache})["records"][0],
            "cache_dir": cache})["record"]
        cls.ccl4 = chemistry_worker.handle({"action": "generate", "record":
            chemistry_worker.handle({"action": "resolve", "kind": "smiles", "text": "ClC(Cl)(Cl)Cl", "cache_dir": cache})["records"][0],
            "cache_dir": cache})["record"]

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.document = FakeDocument()
        self.clipboard = ""
        self.c4d = types.ModuleType("c4d")
        self.c4d.gui = types.SimpleNamespace(GeDialog=DialogAPI)
        self.c4d.BaseContainer = BaseContainer
        self.c4d.GROUPWEIGHTS_PERCENT_W_CNT = 10
        self.c4d.GROUPWEIGHTS_PERCENT_W_VAL = 20
        self.c4d.MOUSEPOS = -1
        self.c4d.DLG_TYPE_ASYNC = 1
        self.c4d.BFM_WEIGHTS_CHANGED = 999
        self.c4d.BFM_INPUT = 100
        self.c4d.BFM_INPUT_DEVICE = 101
        self.c4d.BFM_INPUT_KEYBOARD = 102
        self.c4d.BFM_INPUT_VALUE = 103
        self.c4d.BFM_INPUT_CHANNEL = 104
        self.c4d.BFM_INPUT_ASC = 105
        self.c4d.KEY_ENTER = 61709
        self.c4d.BFM_GETCURSORINFO = 777
        self.c4d.documents = types.SimpleNamespace(GetActiveDocument=lambda: self.document)
        self.c4d.Vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        self.c4d.DR_COLORFIELD_NO_BRIGHTNESS = 1
        self.c4d.EventAdd = lambda: None
        self.c4d.GetStringFromClipboard = lambda: self.clipboard
        builder = types.ModuleType("scimol_c4d.c4d_builder")
        builder.is_managed = lambda obj: isinstance(obj, Root)
        builder.read_model = lambda root: (copy.deepcopy(root.record), copy.deepcopy(root.style))
        self.builds = []

        def build_model(document, record, style, replace_root=None):
            self.builds.append((copy.deepcopy(record), copy.deepcopy(style), replace_root))
            return Root(document, record, style)

        builder.build_model = build_model
        modules = {"c4d": self.c4d, "scimol_c4d.c4d_builder": builder}
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        spec = importlib.util.spec_from_file_location("scimol_c4d.ui", PROJECT / "scimol_c4d/ui.py")
        self.ui = importlib.util.module_from_spec(spec)
        previous = sys.modules.get("scimol_c4d.ui")
        sys.modules["scimol_c4d.ui"] = self.ui
        self.addCleanup(lambda: sys.modules.__setitem__("scimol_c4d.ui", previous)
                        if previous is not None else sys.modules.pop("scimol_c4d.ui", None))
        spec.loader.exec_module(self.ui)
        self.ui.c4d_builder = builder
        bspec = importlib.util.spec_from_file_location("scimol_c4d._smart_browser_test", PROJECT / "scimol_c4d/browser_ui.py")
        self.browser = importlib.util.module_from_spec(bspec)
        bspec.loader.exec_module(self.browser)
        self.browser.c4d_builder = builder
        self.dialog = self.browser.BrowserDialog()
        self.dialog.backend = FakeBackend()
        self.dialog.preview_backend = FakeBackend()
        self.dialog.library = Library(Path(self.temp.name) / "favorites")
        self.dialog.usage = self.ui.UsageStore(Path(self.temp.name) / "usage")
        self.dialog._cards = lambda: None
        self.dialog.LayoutFlushGroup = lambda _id: None
        self.dialog.LayoutChanged = lambda _id: None
        self.dialog.AddButton = lambda *args, **kwargs: None
        self.dialog._set_style(self.dialog.style)

    def test_stick_mode_and_color_presets(self):
        b, d = self.browser, self.dialog
        d.records = [copy.deepcopy(self.ethanol)]
        d._select(0)
        d.SetFloat(b.ATOM_RADIUS, 3.0)
        d.Command(b.ATOM_RADIUS, None)
        d.Command(b.BALL_STICK, None)
        saved_bs = d._get_style()["ball_stick_radius"]

        d.Command(b.STICK_MODE, None)
        stick = d._get_style()
        self.assertEqual(stick["representation"], "continuous")
        self.assertAlmostEqual(stick["atom_radius"], 0.12)
        self.assertAlmostEqual(stick["bond_radius"], 0.10)
        self.assertEqual(stick["ball_stick_radius"], saved_bs)

        d.Command(b.BALL_STICK, None)
        self.assertEqual(d._get_style()["representation"], "ball_stick")
        self.assertAlmostEqual(d._get_style()["atom_radius"], saved_bs)

        d.SetInt32(b.COLOR_PRESET, 2)  # Nature 银灰学术
        d.Command(b.COLOR_PRESET, None)
        self.assertEqual(d._get_style()["element_colors"]["C"], [0.32, 0.35, 0.39])
        self.assertEqual(d._get_style()["bond_color"], [0.76, 0.78, 0.82])

        d.SetInt32(b.COLOR_PRESET, 1)  # 经典 CPK
        d.Command(b.COLOR_PRESET, None)
        self.assertNotIn("C", d._get_style()["element_colors"])

        d.SetInt32(b.COLOR_PRESET, 5)  # 与可竹青（品牌）
        d.Command(b.COLOR_PRESET, None)
        self.assertEqual(d._get_style()["element_colors"]["C"], [0.16, 0.20, 0.26])
        self.assertEqual(d._get_style()["bond_color"], [0.74, 0.78, 0.82])
        yuke_spec = dict(b.COLOR_PRESETS)["与可竹青（品牌）"]
        self.assertEqual(yuke_spec["elements"]["N"], [0.06, 0.46, 0.43])
        self.assertEqual(yuke_spec["elements"]["F"], [0.18, 0.83, 0.75])

    def test_brand_logo_assets_and_bottom_right_structure_details_layout(self):
        b = self.browser
        for fname in ("yuke_lockup_dark.png", "yuke_lockup_light.png"):
            self.assertTrue((PROJECT / "assets" / fname).is_file(), fname)
        for svg in ("yuke-lockup-dark.svg", "yuke-lockup-light.svg", "yuke-icon-micro.svg", "yuke-mark-dark.svg"):
            self.assertTrue((PROJECT / "assets" / "brand" / svg).is_file(), svg)

        layout_src = (PROJECT / "scimol_c4d" / "browser_layout.py").read_text(encoding="utf-8")
        self.assertIn("add_brand_logo(", layout_src)
        self.assertNotIn("ids.DETAILS", layout_src)
        footer_src = layout_src.split("p.GroupBegin(25,", 1)[1]
        self.assertIn("ids.RIGHT_TOGGLE", footer_src)
        self.assertIn('"结构详情"', footer_src)
        self.assertGreater(b.BRAND_LOGO, 0)

    def test_context_aware_controls_disable_inapplicable_options(self):
        b, d = self.browser, self.dialog
        d._display(self.ccl4)
        self.assertFalse(d.enabled[b.BOND_MODE])
        self.assertFalse(d.enabled[b.SPACING_SLIDER])
        self.assertFalse(d.enabled[b.HYDROGENS])

        d.records = [copy.deepcopy(self.ethanol)]
        d._select(0)
        self.assertTrue(d.enabled[b.HYDROGENS])
        self.assertTrue(d.enabled[b.BOND_SLIDER])
        d.Command(b.SPACE_FILL, None)
        self.assertFalse(d.enabled[b.BOND_SLIDER])
        self.assertFalse(d.enabled[b.CYLINDER_SLIDER])
        self.assertFalse(d.enabled[b.BOND_COLOR])
        d.Command(b.BALL_STICK, None)
        self.assertTrue(d.enabled[b.BOND_SLIDER])
        self.assertTrue(d.enabled[b.BOND_COLOR])

    def test_rebind_active_takes_over_finished_scene_model(self):
        b, d = self.browser, self.dialog
        d.records = [copy.deepcopy(self.ethanol)]
        d._select(0)
        root = d.bound_root
        d.Command(b.FINISH, None)
        self.assertFalse(d.session_active)
        self.assertIsNone(d.bound_root)

        self.document.active = root
        d._poll_due = 0.0
        d.Timer(None)
        self.assertTrue(d.enabled[b.REBIND_ACTIVE])
        self.assertIn("已完成", d.GetString(b.STATUS))

        d.Command(b.REBIND_ACTIVE, None)
        self.assertTrue(d.session_active)
        self.assertIs(d.bound_root, root)
        self.assertFalse(d.enabled[b.REBIND_ACTIVE])

    def test_paste_search_and_enter_key_trigger_resolve(self):
        b, d = self.browser, self.dialog
        self.clipboard = "  SMILES: CCO  "
        d.Command(b.PASTE_SEARCH, None)
        self.assertEqual(d.GetString(b.INPUT), "CCO")
        self.assertEqual(d.backend.submitted[-1][1]["text"], "CCO")

        d.SetString(b.INPUT, "C₆H₁₂O₆")
        d.IsActive = lambda cid: cid == b.INPUT

        class KeyMsg:
            def __init__(self, values):
                self.values = values

            def GetId(self):
                return values_id

            def GetInt32(self, k):
                return self.values.get(k, 0)

            def GetString(self, k):
                return ""

        values_id = self.c4d.BFM_INPUT
        msg = KeyMsg({self.c4d.BFM_INPUT_DEVICE: self.c4d.BFM_INPUT_KEYBOARD,
                      self.c4d.BFM_INPUT_VALUE: 1,
                      self.c4d.BFM_INPUT_CHANNEL: self.c4d.KEY_ENTER})
        self.assertTrue(d.Message(msg, None))
        self.assertEqual(d.backend.submitted[-1][1]["text"], "C6H12O6")


class SmartAtomSelectorTests(unittest.TestCase):
    def setUp(self):
        sdk = types.ModuleType("c4d")
        sdk.gui = types.SimpleNamespace(GeUserArea=object, GeDialog=object, SubDialog=object)
        for index, name in enumerate((
            "BFM_INPUT_DEVICE", "BFM_INPUT_MOUSE", "BFM_INPUT_CHANNEL",
            "BFM_INPUT_MOUSELEFT", "BFM_INPUT_MOUSERIGHT", "BFM_INPUT_VALUE",
            "BFM_INPUT_X", "BFM_INPUT_Y", "BFM_INPUT_QUALIFIER",
            "QUALIFIER_SHIFT", "QUALIFIER_CTRL", "BFM_GETCURSORINFO",
            "RESULT_BUBBLEHELP", "RESULT_CURSOR", "MOUSE_SELECT_RECT",
            "MOUSEDRAGFLAGS_DONTHIDEMOUSE", "MOUSEDRAGRESULT_CONTINUE",
            "MOUSEDRAGRESULT_FINISHED", "MOUSEDRAGRESULT_ESCAPE",
        ), 1):
            setattr(sdk, name, index)
        self.sdk = sdk
        self.patch = patch.dict(sys.modules, {"c4d": sdk})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        spec = importlib.util.spec_from_file_location(
            "scimol_c4d._smart_atom_selector_test", PROJECT / "scimol_c4d/atom_selector.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def _panel(self):
        panel = self.module.AtomSelectionPanel(lambda *_args: None, lambda: None)
        panel._image.GetWidth = lambda: 360
        panel._image.GetHeight = lambda: 280
        panel._image.positions = {
            0: (60, 100), 1: (120, 100), 2: (120, 160), 3: (60, 160),
            4: (200, 100), 5: (260, 100), 6: (230, 160),
        }
        panel._image.bonds = {
            "0:1": (0, 1), "1:2": (1, 2), "2:3": (2, 3), "0:3": (0, 3),
            "1:4": (1, 4), "4:5": (4, 5), "5:6": (5, 6), "4:6": (4, 6),
        }
        panel._record = {
            "atoms": [{"id": i, "element": "C"} for i in range(7)],
            "bonds": [
                {"a": 0, "b": 1, "order": 2, "aromatic": False},
                {"a": 1, "b": 2, "order": 1, "aromatic": False},
                {"a": 2, "b": 3, "order": 1, "aromatic": False},
                {"a": 0, "b": 3, "order": 1, "aromatic": False},
                {"a": 1, "b": 4, "order": 1, "aromatic": False},
                {"a": 4, "b": 5, "order": 1, "aromatic": False},
                {"a": 5, "b": 6, "order": 1, "aromatic": False},
                {"a": 4, "b": 6, "order": 1, "aromatic": False},
            ],
        }
        panel.ring_options = self.module.ring_center_options(panel._record)
        panel._layout_ready = False
        return panel

    def test_shift_and_ctrl_selection(self):
        panel = self._panel()
        panel._select_box(60, 100, 60, 100)
        self.assertEqual(panel.selected_ids, {0})
        panel._select_box(120, 100, 120, 100, shift=True)
        self.assertEqual(panel.selected_ids, {0, 1})
        self.assertEqual(panel.selected_bonds, {"0:1"})
        panel._select_box(60, 100, 60, 100, ctrl=True)
        self.assertEqual(panel.selected_ids, {1})
        panel._select_box(90, 100, 90, 100, ctrl=True)
        self.assertEqual(panel.selected_bonds, set())
        panel._select_box(50, 90, 130, 170, shift=True)
        self.assertEqual(panel.selected_ids, {0, 1, 2, 3})

    def test_select_ring_completion_cycling_and_invert(self):
        panel = self._panel()
        panel.selected_ids = {0}
        panel.Command(self.module.SELECT_RING, None)
        self.assertEqual(panel.selected_ids, {0, 1, 2, 3})
        self.assertEqual(panel.selected_bonds, {"0:1", "1:2", "2:3", "0:3"})
        panel.Command(self.module.SELECT_RING, None)
        self.assertEqual(panel.selected_ids, {4, 5, 6})
        panel.Command(self.module.INVERT_SELECT, None)
        self.assertEqual(panel.selected_ids, {0, 1, 2, 3})

    def test_hover_updates_hover_state_and_tooltip(self):
        panel = self._panel()
        area = panel._image
        area.Global2Local = lambda: {"x": 0, "y": 0}
        redraws = []
        area.Redraw = lambda: redraws.append(1)

        class HoverMsg(dict):
            def GetId(self):
                return self_id

            def GetInt32(self, k):
                return self.get(k, 0)

        class Result(dict):
            def SetId(self, v):
                self["id"] = v

            def SetString(self, k, v):
                self[k] = v

            def SetInt32(self, k, v):
                self[k] = v

        self_id = self.sdk.BFM_GETCURSORINFO
        res1 = Result()
        area.Message(HoverMsg({self.sdk.BFM_INPUT_X: 60, self.sdk.BFM_INPUT_Y: 100}), res1)
        self.assertEqual(area.hover_atom, 0)
        self.assertIn("原子 C #0", res1[self.sdk.RESULT_BUBBLEHELP])
        self.assertEqual(len(redraws), 1)

        res2 = Result()
        area.Message(HoverMsg({self.sdk.BFM_INPUT_X: 90, self.sdk.BFM_INPUT_Y: 100}), res2)
        self.assertIsNone(area.hover_atom)
        self.assertEqual(area.hover_bond, "0:1")
        self.assertIn("双键", res2[self.sdk.RESULT_BUBBLEHELP])


class BrandLogoAreaTests(unittest.TestCase):
    def test_theme_aware_brand_logo_renders_clean_lockup(self):
        draws = []

        class FakeArea:
            def __init__(self):
                self._w = 120
                self._h = 28

            def OffScreenOn(self):
                pass

            def GetWidth(self):
                return self._w

            def GetHeight(self):
                return self._h

            def DrawSetPen(self, color):
                draws.append(("pen", color))

            def DrawRectangle(self, *args):
                draws.append(("rect", args))

            def GetColorRGB(self, _col):
                return self._rgb

            def DrawBitmap(self, bmp, dx, dy, dw, dh, sx, sy, bw, bh, flags):
                draws.append(("bmp", bmp.path, dw, dh))

        class FakeBitmap:
            def InitWith(self, path):
                self.path = path
                return (1, False)

            def GetBw(self):
                return 381

            def GetBh(self):
                return 104

        sdk = types.ModuleType("c4d")
        sdk.gui = types.SimpleNamespace(GeUserArea=FakeArea, MessageDialog=lambda text: draws.append(("dialog", text)))
        sdk.bitmaps = types.SimpleNamespace(BaseBitmap=FakeBitmap)
        sdk.COLOR_BG = 1
        sdk.IMAGERESULT_OK = 1
        sdk.BMP_NORMALSCALED = 2
        sdk.BMP_ALLOWALPHA = 4
        sdk.BFH_RIGHT = 8
        sdk.BFH_LEFT = 16
        sdk.BFV_CENTER = 32

        with patch.dict(sys.modules, {"c4d": sdk}):
            spec = importlib.util.spec_from_file_location(
                "scimol_c4d._native_ui_brand_test", PROJECT / "scimol_c4d/native_ui.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            class FakeHost:
                def __init__(self):
                    self.attached = None

                def AddUserArea(self, *_args, **_kwargs):
                    pass

                def AttachUserArea(self, area, identifier):
                    self.attached = (identifier, area)

            host = FakeHost()
            area = mod.add_brand_logo(host, 1564, width=104, height=28)
            self.assertEqual(host.attached, (1564, area))
            area._rgb = {"r": 44, "g": 46, "b": 50}
            area.DrawMsg(0, 0, 120, 28, None)
            self.assertTrue(draws[-1][1].endswith("yuke_lockup_dark.png"))
            area._rgb = {"r": 240, "g": 242, "b": 245}
            area.DrawMsg(0, 0, 120, 28, None)
            self.assertTrue(draws[-1][1].endswith("yuke_lockup_light.png"))


if __name__ == "__main__":
    unittest.main()
