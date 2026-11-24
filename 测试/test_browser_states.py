"""State regressions for the real BrowserDialog with a small C4D stand-in."""

import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from 测试.test_ui_logic import FakeBackend, FakeDialog, FakeDocument
from scimol_c4d import chemistry_worker
from scimol_c4d.library import Library
from scimol_c4d.records import normalized_style


PROJECT = Path(__file__).resolve().parents[1]


class DialogAPI(FakeDialog):
    def __init__(self):
        super().__init__()
        self.hidden = {}
        self.loaded_weights = None
        self.float_options = {}
        self.children = {}

    def FreeChildren(self, identifier):
        self.children[identifier] = {}

    def AddChild(self, identifier, index, name):
        self.children.setdefault(identifier, {})[index] = name

    def SetFloat(self, identifier, value, **options):
        self.values[identifier] = value
        self.float_options[identifier] = options

    def SetInt32(self, identifier, value, **unused):
        self.values[identifier] = value

    def HideElement(self, identifier, hidden):
        self.hidden[identifier] = hidden

    def LayoutChanged(self, identifier):
        pass

    def GroupWeightsLoad(self, identifier, weights):
        self.loaded_weights = weights

    def GroupWeightsSave(self, identifier):
        return self.loaded_weights


class BaseContainer(dict):
    def SetInt32(self, key, value):
        self[key] = value

    def SetFloat(self, key, value):
        self[key] = value

    def GetFloat(self, key):
        return self.get(key, 0.0)

    def InsData(self, key, value):
        self[key] = value


class Root:
    def __init__(self, document, record, style):
        self.document = document
        self.record = copy.deepcopy(record)
        self.style = copy.deepcopy(style)

    def IsAlive(self):
        return True

    def GetDocument(self):
        return self.document

    def GetUp(self):
        return None


class Editor:
    def __init__(self):
        self.groups = {}
        self.groups_dirty = False
        self.selected_ids = set()
        self.selected_bonds = set()
        self._record = None
        self._image = types.SimpleNamespace(bitmap=None, positions={}, Redraw=lambda: None)
        self.editing = False
        self.opened = False

    def IsOpen(self):
        return self.opened

    def Close(self):
        self.opened = False

    def Open(self, *args, **kwargs):
        self.opened = True
        return True

    def set_record(self, record):
        self._record = copy.deepcopy(record)

    def set_appearance(self, style):
        self.appearance = copy.deepcopy(style)

    def set_groups(self, groups):
        self.groups = copy.deepcopy(groups)
        self.groups_dirty = False

    def set_editing(self, value):
        self.editing = bool(value)


class BrowserStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cache = str(Path(cls.fixture.name) / "cache")
        cls.source = chemistry_worker.handle({"action": "resolve", "kind": "smiles",
                                               "text": "CCO", "cache_dir": cache})["records"][0]
        cls.ready = chemistry_worker.handle({"action": "generate", "record": cls.source,
                                              "cache_dir": cache})["record"]

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.document = FakeDocument()
        self.c4d = types.ModuleType("c4d")
        self.c4d.gui = types.SimpleNamespace(GeDialog=DialogAPI)
        self.c4d.BaseContainer = BaseContainer
        self.c4d.GROUPWEIGHTS_PERCENT_W_CNT = 10
        self.c4d.GROUPWEIGHTS_PERCENT_W_VAL = 20
        self.c4d.MOUSEPOS = -1
        self.c4d.DLG_TYPE_ASYNC = 1
        self.c4d.documents = types.SimpleNamespace(GetActiveDocument=lambda: self.document)
        self.c4d.Vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        self.c4d.DR_COLORFIELD_NO_BRIGHTNESS = 1
        self.c4d.EventAdd = lambda: None
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
        browser_spec = importlib.util.spec_from_file_location(
            "scimol_c4d._browser_state_test", PROJECT / "scimol_c4d/browser_ui.py")
        self.browser = importlib.util.module_from_spec(browser_spec)
        browser_spec.loader.exec_module(self.browser)
        self.browser.c4d_builder = builder
        self.dialog = self.browser.BrowserDialog()
        self.dialog.backend = FakeBackend()
        self.dialog.preview_backend = FakeBackend()
        self.dialog.library = Library(Path(self.temp.name) / "favorites")
        self.dialog.usage = self.ui.UsageStore(Path(self.temp.name) / "usage")
        self.dialog._cards = lambda: None
        self.dialog._set_style(self.dialog.style)

    def test_atom_and_bond_element_colors_are_independent_across_uniform_toggle(self):
        b = self.browser
        d = self.dialog
        d._display(self.ready)
        d.SetInt32(b.ELEMENT, d.available_elements.index("O"))
        d.SetColorField(b.ELEMENT_COLOR, self.c4d.Vector(.2, .3, .4))
        d.Command(b.ELEMENT_COLOR, None)
        d.SetInt32(b.BOND_ELEMENT, d.available_elements.index("H"))
        d.SetColorField(b.BOND_COLOR, self.c4d.Vector(.7, .6, .5))
        d.Command(b.BOND_COLOR, None)
        d.SetBool(b.BOND_MATERIAL, True)
        d.Command(b.BOND_MATERIAL, None)
        d.SetColorField(b.BOND_COLOR, self.c4d.Vector(.1, .2, .3))
        d.Command(b.BOND_COLOR, None)
        d.SetBool(b.BOND_MATERIAL, False)
        d.Command(b.BOND_MATERIAL, None)
        style = d._get_style()
        self.assertEqual(style["element_colors"]["O"], [.2, .3, .4])
        self.assertEqual(style["bond_element_colors"]["H"], [.7, .6, .5])
        self.assertEqual(style["bond_color"], [.1, .2, .3])

    def test_numeric_input_exceeding_slider_limit_retains_value_and_clamps_slider(self):
        b, d = self.browser, self.dialog
        d.SetFloat(b.ATOM_RADIUS, 20.0)
        d.Command(b.ATOM_RADIUS, None)
        self.assertEqual(d.GetFloat(b.ATOM_SLIDER), 5.0)
        self.assertAlmostEqual(d._get_style()["atom_radius"], 1 + 15*.7/4)
        self.assertEqual(d._get_style()["representation"], "continuous")

    def test_size_sliders_support_tenths_without_integer_snapping(self):
        b, d = self.browser, self.dialog
        for number, slider, key, low, high in b.PAIRS[:3]:
            for value in (1.1, 2.3, 3.7, 4.9, 2.6):
                d.SetFloat(slider, value)
                d.Command(slider, None)
                self.assertEqual(d.GetFloat(number), value)
                self.assertAlmostEqual(d._get_style()[key], b.to_physical(key, value))
                self.assertEqual(d.float_options[number]["step"], .1)
                self.assertEqual(d.float_options[slider]["step"], .1)
        d.SetFloat(b.BOND_RADIUS, 2.36)
        d.Command(b.BOND_RADIUS, None)
        self.assertEqual(d.GetFloat(b.BOND_RADIUS), 2.4)
        d.SetInt32(b.SPHERE_SEGMENTS, 31)
        d.Command(b.SPHERE_SEGMENTS, None)
        self.assertEqual(d._get_style()["sphere_segments"], 31)

    def test_loading_precise_legacy_size_does_not_change_saved_geometry(self):
        b, d = self.browser, self.dialog
        style = normalized_style({"atom_radius": .4123, "bond_radius": .09123,
                                  "bond_spacing": .18234})
        d._set_style(style)
        for number, _slider, key, _low, _high in b.PAIRS[:3]:
            self.assertEqual(d.GetFloat(number), round(b.to_display(key, style[key]), 1))
            self.assertEqual(d._get_style()[key], style[key])

    def test_read_model_command_cannot_rebind_a_finished_model(self):
        b, d = self.browser, self.dialog
        self.document.active = Root(self.document, self.ready, normalized_style())
        d.Command(b.READ_MODEL, None)
        self.assertFalse(d.session_active)
        self.assertIsNone(d.bound_root)
        self.assertEqual(self.builds, [])
        self.assertIn("读取已取消", d.GetString(b.STATUS))

    def test_repeat_search_returns_original_records_without_another_request(self):
        b, d = self.browser, self.dialog
        d.SetString(b.INPUT, "example original query")
        d.Command(b.RESOLVE, None)
        d.backend.finish({"ok": True, "records": [self.source]})
        d.Timer(None)
        count = len(d.backend.submitted)
        d.records[0]["name"] = "用户改名"
        d.Command(b.RESOLVE, None)
        self.assertEqual(len(d.backend.submitted), count)
        self.assertEqual(d.records[0]["name"], self.source["name"])
        self.assertFalse(d.search_pending)

    def test_loaded_builtin_alias_search_does_not_start_sidecar(self):
        b, d = self.browser, self.dialog
        local = copy.deepcopy(self.source); local["name"] = "乙醇"
        d.builtins = [local]
        d.SetString(b.INPUT, "酒精"); d.Command(b.RESOLVE, None)
        self.assertEqual(d.records[0]["name"], "乙醇")
        self.assertEqual(d.backend.submitted, [])
        self.assertFalse(d.search_pending)

    def test_search_cache_is_bounded_and_smiles_case_sensitive(self):
        d = self.dialog
        d._cache_search("CO", [self.source])
        d._cache_search("Co", [self.ready])
        self.assertEqual(set(d._resolve_cache), {"CO", "Co"})
        for i in range(101): d._cache_search("query %d" % i, [self.source])
        self.assertEqual(len(d._resolve_cache), 100)
        self.assertNotIn("CO", d._resolve_cache)
        d._cache_search("failed or empty", [])
        self.assertNotIn("failed or empty", d._resolve_cache)

    def test_element_scales_follow_global_size_and_one_resets_the_multiplier(self):
        b, d = self.browser, self.dialog
        d._display(self.ready)
        for element, factor in (("H", .5), ("C", 2.1)):
            d.SetInt32(b.SIZE_ELEMENT, d.available_elements.index(element))
            d.Command(b.SIZE_ELEMENT, None)
            self.assertEqual(d.GetFloat(b.ELEMENT_SIZE), 1.)
            self.assertTrue(d.enabled[b.ELEMENT_SIZE_SLIDER])
            d.SetFloat(b.ELEMENT_SIZE_SLIDER, factor)
            d.Command(b.ELEMENT_SIZE_SLIDER, None)
            self.assertEqual(d.GetFloat(b.ELEMENT_SIZE), factor)
        scales = copy.deepcopy(d._get_style()["element_scales"])
        d.SetFloat(b.ATOM_RADIUS, 3.5)
        d.Command(b.ATOM_RADIUS, None)
        self.assertEqual(d._get_style()["element_scales"], scales)
        self.assertEqual(scales, {"H": .5, "C": 2.1})
        self.assertEqual(d._get_style()["bond_radius_overrides"], {})
        d.SetFloat(b.ELEMENT_SIZE, 1.)
        d.Command(b.ELEMENT_SIZE, None)
        self.assertNotIn("C", d._get_style()["element_scales"])
        self.assertEqual(d.GetFloat(b.ELEMENT_SIZE), 1.)
        self.assertIn("H", d._get_style()["element_scales"])
        d.Command(b.RESET, None)
        self.assertEqual(d._get_style()["element_radius_overrides"], {})
        self.assertEqual(d._get_style()["element_scales"], {})

    def test_slider_reset_changes_only_its_own_parameter(self):
        b, d = self.browser, self.dialog
        d._display(self.ready)
        d._set_style(normalized_style({'atom_radius':.7, 'bond_radius':.13,
                                      'bond_spacing':.3, 'sphere_segments':32,
                                      'cylinder_segments':36, 'element_scales':{'H':.5,'C':2.1}}))
        for _, slider, key, _, _ in b.PAIRS:
            before = copy.deepcopy(d._get_style())
            d.Command(b.SLIDER_RESETS[slider],None)
            after = d._get_style()
            self.assertEqual(after[key],b.DEFAULT_STYLE[key])
            for other in ('atom_radius','bond_radius','bond_spacing','sphere_segments','cylinder_segments','element_scales'):
                if other != key: self.assertEqual(after[other],before[other])
        d.SetInt32(b.SIZE_ELEMENT,d.available_elements.index('C'))
        d.Command(b.SLIDER_RESETS[b.ELEMENT_SIZE_SLIDER],None)
        self.assertEqual(d._get_style()['element_scales'],{'H':.5})
        self.assertEqual(d.GetFloat(b.ELEMENT_SIZE),1.)

    def test_element_scale_input_can_exceed_slider_and_preserves_precise_legacy_style(self):
        b, d = self.browser, self.dialog
        d._display(self.ready)
        d._set_style(normalized_style({"atom_radius":.4123,"element_radius_overrides":{"C":.72123}}))
        migrated=copy.deepcopy(d.style)
        self.assertEqual(migrated['element_radius_overrides'], {})
        self.assertEqual(d._get_style()['element_scales'], migrated['element_scales'])
        d.SetFloat(b.ELEMENT_SIZE, 8.4); d.Command(b.ELEMENT_SIZE, None)
        self.assertEqual(d._get_style()['element_scales']['C'], 8.4)
        self.assertEqual(d.GetFloat(b.ELEMENT_SIZE_SLIDER), 3.)

    def test_all_element_menus_match_current_structure_and_preserve_symbols(self):
        b, d = self.browser, self.dialog
        self.assertEqual(d.available_elements, ())
        self.assertFalse(d.enabled[b.ELEMENT_COLOR])
        d._display(self.ready)
        self.assertEqual(d.available_elements, ('C','H','O'))
        for identifier in (b.ELEMENT,b.BOND_ELEMENT,b.SIZE_ELEMENT):
            self.assertEqual(tuple(d.children[identifier].values()), ('C','H','O'))
            d.SetInt32(identifier,d.available_elements.index('O'))
        water=chemistry_worker.handle({'action':'resolve','kind':'smiles','text':'O',
                                      'cache_dir':str(Path(self.temp.name)/'cache')})['records'][0]
        water=chemistry_worker.handle({'action':'generate','record':water,
                                      'cache_dir':str(Path(self.temp.name)/'cache')})['record']
        d.style['element_scales']['F']=1.2
        d._display(water)
        self.assertEqual(d.available_elements, ('H','O'))
        for identifier in (b.ELEMENT,b.BOND_ELEMENT,b.SIZE_ELEMENT):
            self.assertEqual(tuple(d.children[identifier].values()), ('H','O'))
            self.assertEqual(d._chosen_element(identifier),'O')
        self.assertNotIn('F',d.available_elements)

    def test_element_menus_include_uncommon_elements_without_color_failure(self):
        b, d = self.browser, self.dialog
        record=chemistry_worker.handle({'action':'resolve','kind':'smiles','text':'C[Si](C)(C)C',
                                       'cache_dir':str(Path(self.temp.name)/'cache')})['records'][0]
        d._display(record)
        self.assertEqual(d.available_elements, ('C','Si'))
        for identifier in (b.ELEMENT,b.BOND_ELEMENT,b.SIZE_ELEMENT):
            d.SetInt32(identifier,d.available_elements.index('Si'))
            d.Command(identifier,None)
        d.SetFloat(b.ELEMENT_SIZE,1.6); d.Command(b.ELEMENT_SIZE,None)
        self.assertEqual(d._get_style()['element_scales']['Si'],1.6)

    def test_independent_segments_and_legacy_quality_fallback(self):
        b, d = self.browser, self.dialog
        old_style = normalized_style({"quality": 36})
        self.assertEqual((old_style["sphere_segments"], old_style["cylinder_segments"]),
                         (36, 36))
        d._set_style(old_style)
        d.SetInt32(b.SPHERE_SEGMENTS, 48)
        d.Command(b.SPHERE_SEGMENTS, None)
        d.SetInt32(b.CYLINDER_SEGMENTS, 20)
        d.Command(b.CYLINDER_SEGMENTS, None)
        self.assertEqual((d._get_style()["sphere_segments"],
                          d._get_style()["cylinder_segments"]), (48, 20))

    def test_search_and_empty_folder_clear_previous_target(self):
        b, d = self.browser, self.dialog
        d.current_record = copy.deepcopy(self.ready)
        d.bound_root = Root(self.document, self.ready, normalized_style())
        for records, view in (([self.source], "resolve"), ([], "folder:空文件夹")):
            with self.subTest(view=view):
                d._show_records(records, view)
                self.assertIsNone(d.current_record)
                self.assertIsNone(d.bound_root)
                self.assertIsNone(d._apply_current())
                self.assertEqual(self.builds, [])
                self.assertEqual(d.backend.submitted, [])

    def test_new_root_does_not_inherit_previous_plane_groups(self):
        d = self.dialog
        d.editor = Editor()
        first = Root(self.document, self.ready, normalized_style())
        second = Root(self.document, self.ready, normalized_style())
        d.right_visible = True
        d._set_editor_visible(True)
        d._bind_root(first)
        draft = {"1": {"atom_ids": [0, 1], "origin": [0, 0, 0],
                       "normal": [0, 0, 1], "color": [1, 0, 0]}}
        d.editor.groups = copy.deepcopy(draft)
        d.editor.groups_dirty = True
        d._bind_root(second)
        self.assertEqual(d.editor.groups, {})
        self.assertIs(d.bound_root, second)
        self.assertEqual(d.selector_drafts, [])
        d._bind_root(first)
        self.assertEqual(d.editor.groups, {})
        self.assertFalse(d.editor.groups_dirty)

    def test_finish_cancels_async_generation_and_does_not_rebind_selected_model(self):
        d = self.dialog
        first = Root(self.document, self.source, normalized_style())
        second = Root(self.document, self.ready, normalized_style())
        self.document.active = first
        d.bound_root = first
        d.session_active = True
        d._session_document = self.document
        d.current_record = copy.deepcopy(self.source)
        d.SetString(self.browser.LABEL, "乙醇")
        d._apply_current()
        token, _payload, context = d.backend.submitted[-1]
        self.assertIs(context["replacement"], first)
        d.Command(self.browser.FINISH, None)
        self.document.active = second
        d.backend.finish({"ok": True, "record": self.ready}, token, context)
        d.Timer(None)
        self.assertEqual(self.builds, [])
        self.assertFalse(d.session_active)
        self.assertIsNone(d.bound_root)
        self.assertIn("已完成", d.GetString(self.browser.STATUS))

    def test_structure_details_toggle_preserves_draft_and_left_sidebar(self):
        b, d = self.browser, self.dialog
        from unittest.mock import Mock
        follower = d._window_follower = Mock()
        weights = copy.deepcopy(d.pane_weights)
        d.editor = Editor()
        d.current_record = copy.deepcopy(self.ready)
        self.assertFalse(d.right_visible)
        self.assertFalse(d.editing)
        d.Command(b.RIGHT_TOGGLE, None)
        follower.start.assert_called_once_with(d, d.editor)
        self.assertTrue(d.right_visible)
        self.assertTrue(d.editing)
        self.assertTrue(d.editor.editing)
        d.editor.groups = {"1": {"atom_ids": [0]}}
        d.editor.groups_dirty = True
        d.Command(b.LEFT_TOGGLE, None)
        self.assertTrue(d.left_visible)
        self.assertFalse(d.hidden.get(b.LIBRARY_GROUP, False))
        d.Command(b.RIGHT_TOGGLE, None)
        follower.stop.assert_called_once_with()
        self.assertEqual(d.pane_weights, weights)
        self.assertFalse(d.right_visible)
        self.assertFalse(d.editing)
        self.assertFalse(d.editor.editing)
        self.assertTrue(d.editor.groups_dirty)
        self.assertEqual(d.editor.groups["1"]["atom_ids"], [0])
        d.Command(b.RIGHT_TOGGLE, None)
        self.assertEqual(follower.start.call_count, 2)
        self.assertTrue(d.right_visible)
        self.assertTrue(d.editing)
        self.assertTrue(d.editor.IsOpen())
        self.assertNotIn(b.EDITOR_GROUP, d.hidden)

    def test_local_radii_preserve_source_and_uncommitted_planes(self):
        d = self.dialog
        d.current_record = copy.deepcopy(self.ready)
        d.editor = Editor()
        d.editor.groups = {"1": {"atom_ids": [0]}}
        d.editor.groups_dirty = True
        original = copy.deepcopy(d.current_record)
        d._set_style(normalized_style())
        d._apply_local_appearance("atoms", [0], .6)
        d._apply_local_appearance("bonds", ["0:1"], .16)
        style = d._get_style()
        self.assertEqual(style["atom_radius_overrides"], {"0": .6})
        self.assertEqual(style["bond_radius_overrides"], {"0:1": .16})
        self.assertEqual(style["plane_groups"], {})
        self.assertTrue(d.editor.groups_dirty)
        self.assertEqual(d.editor.groups, {"1": {"atom_ids": [0]}})
        self.assertEqual(d.current_record, original)
        self.assertEqual(self.builds, [])
        d._apply_local_appearance("reset", {"atoms": [0], "bonds": ["0:1"]}, None)
        self.assertEqual(d._get_style()["atom_radius_overrides"], {})
        self.assertEqual(d._get_style()["bond_radius_overrides"], {})
        self.assertTrue(d.editor.groups_dirty)

    def test_local_radii_do_not_accept_foreign_structure_selection(self):
        d = self.dialog
        d.current_record = copy.deepcopy(self.ready)
        before = d._get_style()
        for kind, keys in (("atoms", [999]), ("bonds", ["0:999"])):
            with self.assertRaises(ValueError):
                d._apply_local_appearance(kind, keys, .5)
        self.assertEqual(d._get_style(), before)

    def test_rename_preview_without_binding_keeps_original_record(self):
        b, d = self.browser, self.dialog
        original = copy.deepcopy(self.ready)
        d.records = [copy.deepcopy(self.ready)]
        d.selected = 0
        d.current_record = copy.deepcopy(self.ready)
        self.c4d.gui.ShowPopupDialog = lambda *_args: 1
        self.c4d.gui.InputDialog = lambda *_args: "用户命名"
        d._resource_menu(0)
        self.assertIsNone(d.bound_root)
        self.assertEqual(d.current_record["name"], "用户命名")
        self.assertEqual(d.records[0]["name"], "用户命名")
        self.assertEqual(d.current_record["atoms"], original["atoms"])
        self.assertEqual(self.ready, original)
        self.assertEqual(self.builds, [])

    def test_configuration_save_as_and_reset_keep_source_atoms(self):
        b, d = self.browser, self.dialog
        original = copy.deepcopy(self.ready)
        d.current_record = copy.deepcopy(self.ready)
        d.preset_origin_record = copy.deepcopy(self.ready)
        d.SetString(b.LABEL, "科研配置")
        d.SetFloat(b.ATOM_RADIUS, .55)
        d.Command(b.CONFIG_SAVE, None)
        first_id = d.configuration_id
        self.assertIsNotNone(first_id)
        self.assertEqual(len(d.library.all()), 1)
        prompts = []
        self.c4d.gui.InputDialog = lambda title, default: prompts.append((title, default)) or default
        d.Command(b.CONFIG_SAVE_AS, None)
        entries = d.library.all()
        self.assertEqual([entry["label"] for entry in entries],
                         ["科研配置", "科研配置 1"])
        self.assertNotEqual(entries[0]["id"], entries[1]["id"])
        self.assertEqual(prompts, [("另存为配置", "科研配置")])
        common = d._folder_records("common")
        self.assertEqual({r["configuration_id"] for r in common}, {entry["id"] for entry in entries})
        d.editor = Editor()
        d.editor.groups = {"1": {"atom_ids": [0]}}
        d.editor.groups_dirty = True
        d.Command(b.RESET, None)
        self.assertEqual(d._get_style()["atom_radius"], normalized_style()["atom_radius"])
        self.assertEqual(d.editor.groups, {})
        self.assertEqual(d.current_record["atoms"], original["atoms"])
        self.assertEqual(d.preset_origin_record["atoms"], original["atoms"])
        self.assertEqual(self.ready, original)

    def test_all_folder_and_bulk_delete_keep_active_preview(self):
        d = self.dialog
        first = d.library.save_configuration(self.ready, normalized_style(), "第一配置")
        second = d.library.save_configuration(self.ready, normalized_style(), "第二配置")
        d.builtins = [copy.deepcopy(self.ready)]
        d._browse_folder("all")
        self.assertEqual(len(d.records), 3)
        d.current_record = copy.deepcopy(self.ready)
        original = copy.deepcopy(d.current_record)
        d.selected_cards = {i for i,r in enumerate(d.records) if r.get("configuration_id")}
        d._delete_resources()
        self.assertEqual(d.library.all(), [])
        self.assertEqual(len(d.records), 1)
        self.assertEqual(d.current_record, original)
        self.assertEqual(self.builds, [])
        self.assertEqual(d.selected_cards, set())
        self.assertIn("all", {node["id"] for node in d.folder_nodes})
        self.assertNotIn("未分类", {node["name"] for node in d.folder_nodes})

    def test_save_as_cancel_keeps_configuration_unchanged(self):
        d, b = self.dialog, self.browser
        d.current_record = copy.deepcopy(self.ready)
        self.c4d.gui.InputDialog = lambda *_args: None
        d.Command(b.CONFIG_SAVE_AS, None)
        self.assertEqual(d.library.all(), [])
        self.assertIsNone(d.configuration_id)

    def test_no_drag_generation_even_without_active_preview(self):
        d = self.dialog
        d.records = [copy.deepcopy(self.ready)]
        area=types.SimpleNamespace(HandleMouseDrag=lambda *_: self.fail('unexpected drag'))
        self.assertFalse(d._drag_asset(0,None,area))
        self.assertFalse(d.session_active)
        self.assertEqual(self.builds,[])

    def test_apply_commits_plane_draft_but_live_style_update_keeps_it_pending(self):
        from scimol_c4d.display_geometry import make_plane_group
        b, d = self.browser, self.dialog
        d.current_record = copy.deepcopy(self.ready)
        d.session_active = True
        d._session_document = self.document
        d.SetString(b.LABEL, self.ready['name'])
        d.editor = Editor()
        group = make_plane_group(self.ready, [0, 1, 2])
        d.editor.groups = {'1': {**group, 'color': [.2, .5, .8]}}
        d.editor.groups_dirty = True
        # Observe the style supplied to a real builder, independent of editor
        # redisplay/binding details already covered by the root-switch test.
        builds = []
        d._build = lambda record, style, doc, root: builds.append(style)
        d._apply_current(commit_planes=False)
        self.assertEqual(builds[-1]['plane_groups'], {})
        self.assertTrue(d.editor.groups_dirty)
        d._apply_current()
        self.assertEqual(builds[-1]['plane_groups'], d.editor.groups)
        self.assertFalse(d.editor.groups_dirty)

    def test_single_select_generates_then_finish_keeps_model_unchanged(self):
        b, d = self.browser, self.dialog
        d.records = [copy.deepcopy(self.ready)]
        d._select(0)
        self.assertEqual(len(self.builds), 1)
        first = d.bound_root
        self.assertTrue(d.session_active)
        self.assertIs(self.builds[0][2], None)
        d.SetFloat(b.BOND_RADIUS, 12)
        d.Command(b.BOND_RADIUS, None)
        d._live_due = 0
        d.Timer(None)
        self.assertEqual(len(self.builds), 2)
        self.assertIs(self.builds[-1][2], first)
        d.Command(b.FINISH, None)
        completed_builds = len(self.builds)
        d.SetFloat(b.BOND_RADIUS, 14)
        d.Command(b.BOND_RADIUS, None)
        d._live_due = 0
        d.Timer(None)
        self.assertEqual(len(self.builds), completed_builds)
        self.assertIsNone(d.bound_root)
        d._select(0)
        self.assertEqual(len(self.builds), completed_builds+1)
        self.assertIsNone(self.builds[-1][2])

    def test_other_card_replaces_active_preview_without_finish(self):
        b, d = self.browser, self.dialog
        first=copy.deepcopy(self.ready); first['configuration_id']='first'
        second=copy.deepcopy(self.ready); second['configuration_id']='second'
        second['name']='第二个结构'
        d.records=[first,second]
        d._select(0)
        root=d.bound_root
        d.SetFloat(b.ATOM_RADIUS,3)
        d.Command(b.ATOM_RADIUS,None)
        due=d._live_due; token=d.backend.generation
        self.assertTrue(d._select(1))
        self.assertEqual(len(self.builds),2)
        self.assertIs(self.builds[-1][2],root)
        self.assertEqual(d.current_record['configuration_id'],'second')
        self.assertEqual(d.selected_cards,{1})
        self.assertEqual(d.GetFloat(b.ATOM_RADIUS),1)
        self.assertIsNone(d._live_due)
        d.Command(b.FINISH,None)
        self.assertTrue(d._select(1))
        self.assertEqual(d.current_record['configuration_id'],'second')
        self.assertIsNone(self.builds[-1][2])

    def test_folder_search_and_context_do_not_detach_active_model(self):
        d=self.dialog
        first=copy.deepcopy(self.ready); second=copy.deepcopy(self.ready)
        first['configuration_id']='first'; second['configuration_id']='second'
        d.records=[first]; d._select(0)
        root=d.bound_root; original=copy.deepcopy(d.current_record)
        d.builtins=[second]
        d._browse_folder('all')
        self.assertIs(d.bound_root,root)
        d._show_records([second],'resolve')
        self.assertIs(d.bound_root,root)
        self.assertEqual(d.current_record,original)
        self.c4d.gui.ShowPopupDialog=lambda *_args:0
        d._resource_menu(0)
        self.assertIs(d.bound_root,root)
        self.assertTrue(d.session_active)
        self.assertEqual(d.current_record,original)
        self.assertEqual(len(self.builds),1)

    def test_active_drag_is_rejected_before_any_scene_drop(self):
        d=self.dialog
        d.records=[copy.deepcopy(self.ready)]; d._select(0)
        root=d.bound_root
        drops=[]
        area=types.SimpleNamespace(HandleMouseDrag=lambda *args:drops.append(args))
        self.assertFalse(d._drag_asset(0,None,area))
        self.assertEqual(drops,[])
        self.assertIs(d.bound_root,root)
        self.assertTrue(d.session_active)

    def test_latest_selection_cancels_old_generation_and_uses_latest_adjustments(self):
        d,b=self.dialog,self.browser
        first=copy.deepcopy(self.source); first['configuration_id']='A'
        second=copy.deepcopy(self.source); second['configuration_id']='B'
        d.records=[first,second]
        d._select(0)
        token=d.backend.generation
        context=d.backend.submitted[-1][2]
        self.assertTrue(d.busy)
        d._select(1)
        latest=copy.deepcopy(self.ready); latest['configuration_id']='B'
        old=copy.deepcopy(self.ready); old['configuration_id']='A'
        d.backend.finish({'ok':True,'record':old},token=token,context=context)
        d.SetFloat(b.BOND_RADIUS,4)
        d.Command(b.BOND_RADIUS,None)
        d.Timer(None)
        self.assertEqual(self.builds,[])
        d.backend.finish({'ok':True,'record':latest})
        d.Timer(None)
        self.assertEqual(len(self.builds),1)
        self.assertEqual(self.builds[-1][0]['configuration_id'],'B')
        self.assertAlmostEqual(self.builds[-1][1]['bond_radius'],.14666666666666667)
        self.assertTrue(d.session_active)

    def test_ready_geometry_is_cached_across_folders_and_preserves_new_name(self):
        d=self.dialog
        d.records=[copy.deepcopy(self.source)]
        d._select(0)
        d.backend.finish({'ok':True,'record':self.ready})
        d.Timer(None)
        requests=len(d.backend.submitted)
        source=copy.deepcopy(self.source); source['name']='重新命名'
        d._show_records([source],'resolve')
        d._select(0)
        self.assertEqual(len(d.backend.submitted),requests)
        self.assertEqual(d.current_record['name'],'重新命名')
        self.assertTrue(d.current_record['coordinates_ready'])
        self.assertIsNotNone(self.builds[-1][2])

    def test_material_inheritance_is_enabled_by_default_and_updates_live(self):
        d,b=self.dialog,self.browser
        d.records=[copy.deepcopy(self.ready)]; d._select(0)
        self.assertTrue(self.builds[-1][1]['inherit_materials'])
        self.assertEqual(self.builds[-1][1]['orientation'],'auto')
        d.SetBool(b.MATERIAL_INHERIT,False)
        d.Command(b.MATERIAL_INHERIT,None)
        d._live_due=0; d.Timer(None)
        self.assertFalse(self.builds[-1][1]['inherit_materials'])

    def test_unified_search_has_visible_loading_and_result_states(self):
        d,b=self.dialog,self.browser
        d.SetString(b.INPUT,'CCO')
        d.Command(b.RESOLVE,None)
        self.assertEqual(d.backend.submitted[-1][1]['kind'],'auto')
        self.assertTrue(d.search_pending)
        self.assertEqual(d.folder_current,'search')
        self.assertEqual(d.records,[])
        self.assertIn('正在搜索',d.GetString(b.SEARCH_STATUS))
        d.Timer(None)
        self.assertIn('正在搜索',d.search_message)
        d.backend.finish({'ok':True,'records':[self.source]})
        d.Timer(None)
        self.assertFalse(d.search_pending)
        self.assertIn('找到 1',d.GetString(b.SEARCH_STATUS))
        d._browse_folder('all'); d._browse_folder('search')
        self.assertEqual(len(d.records),1)

    def test_background_preview_does_not_block_live_updates_or_cancel_chemistry(self):
        d,b=self.dialog,self.browser
        d.records=[copy.deepcopy(self.ready)]; d._select(0)
        generation=d.backend.generation
        d._start({'action':'preview','record':self.ready},'theme',structure_key=self.ready['structure_key'])
        self.assertFalse(d.busy)
        self.assertEqual(d.backend.generation,generation)
        d.SetFloat(b.ATOM_RADIUS,3); d.Command(b.ATOM_RADIUS,None)
        due=d._live_due
        d.SetFloat(b.ATOM_RADIUS,4); d.Command(b.ATOM_RADIUS,None)
        self.assertEqual(d._live_due,due)
        d._live_due=0; d.Timer(None)
        self.assertAlmostEqual(self.builds[-1][1]['atom_radius'],.825)
        d.preview_backend.finish({'ok':True,'record':self.source})
        d.Timer(None)
        self.assertTrue(d.current_record['coordinates_ready'])

    def test_search_error_is_visible_and_cancel_stops_loading_state(self):
        d,b=self.dialog,self.browser
        d.SetString(b.INPUT,'unknown'); d.Command(b.RESOLVE,None)
        d.backend.finish({'ok':False,'error':'查询失败'})
        d.Timer(None)
        self.assertFalse(d.search_pending)
        self.assertEqual(d.GetString(b.SEARCH_STATUS),'查询失败')
        d.Command(b.RESOLVE,None); d.Command(b.CANCEL,None)
        self.assertFalse(d.search_pending)
        self.assertEqual(d.search_message,'搜索已取消')

    def test_finish_does_not_cancel_a_search_for_the_next_resource(self):
        d,b=self.dialog,self.browser
        d.records=[copy.deepcopy(self.ready)]; d._select(0)
        d.SetString(b.INPUT,'苯'); d.Command(b.RESOLVE,None)
        token=d.backend.generation
        d.Command(b.FINISH,None)
        self.assertFalse(d.session_active)
        self.assertTrue(d.search_pending)
        self.assertEqual(d.backend.generation,token)
        d.backend.finish({'ok':True,'records':[self.source]}); d.Timer(None)
        self.assertFalse(d.search_pending)
        self.assertEqual(len(d.records),1)

    def test_plane_assignment_and_orientation_reach_live_style_without_update_button(self):
        from scimol_c4d.display_geometry import make_plane_group
        d = self.dialog
        d.records = [copy.deepcopy(self.ready)]
        d.editor = Editor()
        d._select(0)
        group = make_plane_group(self.ready, [0,1,2])
        self.assertTrue(d._apply_plane_groups({"1":{**group,"color":[.2,.5,.8]}}))
        d._apply_orientation("xy", [1])
        d._live_due = 0
        d.Timer(None)
        style = self.builds[-1][1]
        self.assertEqual(style["orientation"], "xy")
        self.assertEqual(style["center_atom_ids"], [1])
        self.assertIn("1", style["plane_groups"])
        self.assertEqual(d.current_record["atoms"], self.ready["atoms"])

    def test_context_save_as_not_offered_for_inactive_multiselection_card(self):
        d = self.dialog
        first = copy.deepcopy(self.ready); first["configuration_id"]="A"
        second = copy.deepcopy(self.ready); second["configuration_id"]="B"
        d.records = [first,second]
        d.current_record = copy.deepcopy(first); d.selected=0
        d.selected_cards={1}
        menus=[]
        self.c4d.gui.ShowPopupDialog=lambda _d,menu,*_args: menus.append(menu) or 0
        d._resource_menu(1)
        self.assertNotIn(2, menus[0])
        self.assertEqual(d.current_record["configuration_id"],"A")


if __name__ == "__main__":
    unittest.main()
