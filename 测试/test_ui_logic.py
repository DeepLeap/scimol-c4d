"""Exercise panel decisions with a tiny C4D stand-in, without claiming host validation."""

import copy
import importlib.util
from pathlib import Path
import queue
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from scimol_c4d import chemistry_worker
from scimol_c4d.library import Library
from scimol_c4d.records import normalized_style


class FakeDialog:
    def __init__(self):
        self.values = {}
        self.enabled = {}
        self.color_options = {}

    def SetString(self, identifier, value):
        self.values[identifier] = value

    def GetString(self, identifier):
        return self.values.get(identifier, "")

    def SetInt32(self, identifier, value):
        self.values[identifier] = value

    def GetInt32(self, identifier):
        return self.values.get(identifier, 0)

    def SetFloat(self, identifier, value, **unused):
        self.values[identifier] = value

    def GetFloat(self, identifier):
        return self.values[identifier]

    def SetBool(self, identifier, value):
        self.values[identifier] = value

    def GetBool(self, identifier):
        return self.values[identifier]

    def SetColorField(self, identifier, color, brightness=1.0, maxbrightness=1.0, flags=0):
        self.values[identifier] = color
        self.color_options[identifier] = (brightness, maxbrightness, flags)

    def GetColorField(self, identifier):
        return {"color": self.values[identifier]}

    def Enable(self, identifier, value):
        self.enabled[identifier] = value

    def SetTimer(self, interval):
        self.timer = interval


class FakeBackend:
    def __init__(self):
        self.results = queue.Queue()
        self.generation = 0
        self.submitted = []

    def cancel(self):
        self.generation += 1

    def submit(self, payload, context):
        self.cancel()
        self.submitted.append((self.generation, copy.deepcopy(payload), context))
        return self.generation

    @staticmethod
    def _log(message):
        pass

    def finish(self, result, token=None, context=None):
        last_token, _, last_context = self.submitted[-1]
        self.results.put((last_token if token is None else token,
                          last_context if context is None else context, result, 0.1))


class FakeDocument:
    def __init__(self):
        self.active = None

    def GetActiveObject(self):
        return self.active

    def SetActiveObject(self, root, selection):
        self.active = root


class FakeRoot:
    def __init__(self, record, style):
        self.record = copy.deepcopy(record)
        self.style = copy.deepcopy(style)

    def GetUp(self):
        return None


class FakeAtomSelector:
    """Only models the panel's lifetime and pending-group handoff."""

    instances = []

    def __init__(self, on_flatten, on_restore, on_selection, on_apply_groups):
        self.open = False
        self.closed = False
        self._record = None
        self.groups = {}
        self.groups_dirty = False
        self.set_groups_calls = 0
        self.__class__.instances.append(self)

    def IsOpen(self):
        return self.open

    def Open(self, *args, **kwargs):
        self.open = True

    def Close(self):
        self.closed = True
        self.open = False

    def set_record(self, record):
        self._record = copy.deepcopy(record)

    def set_groups(self, groups):
        self.set_groups_calls += 1
        self.groups = copy.deepcopy(groups)
        self.groups_dirty = False

    def _status(self, value):
        self.status = value


class UILogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cache = str(Path(cls.fixture_dir.name) / "cache")
        cls.source = chemistry_worker.handle({"action": "resolve", "kind": "smiles",
                                              "text": "CCO", "cache_dir": cache})["records"][0]
        cls.generated = chemistry_worker.handle({"action": "generate", "record": cls.source,
                                                 "cache_dir": cache})["record"]

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.document = FakeDocument()
        self.current_document = {"value": self.document}
        self.builds = []
        c4d = types.ModuleType("c4d")
        c4d.gui = types.SimpleNamespace(GeDialog=FakeDialog, MessageDialog=lambda message: None)
        c4d.documents = types.SimpleNamespace(GetActiveDocument=lambda: self.current_document["value"])
        c4d.storage = types.SimpleNamespace(LoadDialog=lambda **kw: None)
        c4d.Vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        c4d.DR_COLORFIELD_NO_BRIGHTNESS = 1
        c4d.SELECTION_NEW = 1
        c4d.DLG_TYPE_ASYNC = 1
        c4d.EventAdd = lambda: None
        builder = types.ModuleType("scimol_c4d.c4d_builder")
        builder.is_managed = lambda obj: isinstance(obj, FakeRoot)
        builder.read_model = lambda obj: (copy.deepcopy(obj.record), copy.deepcopy(obj.style))

        def build_model(document, record, style, replace_root=None):
            self.builds.append((document, copy.deepcopy(record), copy.deepcopy(style), replace_root))
            return FakeRoot(record, style)

        builder.build_model = build_model
        import scimol_c4d
        self.module_patch = patch.dict(sys.modules, {"c4d": c4d,
                                                     "scimol_c4d.c4d_builder": builder})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.builder_patch = patch.object(scimol_c4d, "c4d_builder", builder, create=True)
        self.builder_patch.start()
        self.addCleanup(self.builder_patch.stop)
        spec = importlib.util.spec_from_file_location("scimol_c4d._ui_logic_test", PROJECT / "scimol_c4d" / "ui.py")
        self.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ui)
        self.dialog = self.ui.MoleculeDialog()
        self.dialog.backend = FakeBackend()
        self.dialog.library = Library(Path(self.temp.name) / "favorites")
        self.dialog.usage = self.ui.UsageStore(Path(self.temp.name) / "usage")
        self.dialog._cards = lambda: None
        self.dialog._set_style(self.dialog.style)

    def use_fake_selector(self):
        FakeAtomSelector.instances.clear()
        stub = types.ModuleType("scimol_c4d.atom_selector")
        stub.AtomSelectionDialog = FakeAtomSelector
        selector_patch = patch.dict(sys.modules, {"scimol_c4d.atom_selector": stub})
        selector_patch.start()
        self.addCleanup(selector_patch.stop)

    def select(self, record):
        self.dialog._show_records([record], "resolve")
        self.dialog._select(0)

    def test_new_lookup_and_failure_leave_no_old_selection_to_generate(self):
        self.select(self.source)
        self.dialog.SetString(self.ui.INPUT, "未知名称")
        self.dialog.Command(self.ui.RESOLVE, None)
        self.assertEqual(self.dialog.records, [])
        self.assertEqual(self.dialog.selected, -1)
        self.dialog.backend.finish({"ok": False, "error": "未找到结构"})
        self.dialog.Timer(None)
        self.dialog.Command(self.ui.GENERATE, None)
        self.assertEqual(self.builds, [])
        self.assertEqual(len(self.dialog.backend.submitted), 1)

    def test_existing_3d_without_ready_hydrogens_runs_generation(self):
        partial = copy.deepcopy(self.generated)
        partial["coordinates_ready"] = False
        partial.pop("record_integrity", None)
        self.select(partial)
        self.dialog.Command(self.ui.GENERATE, None)
        _, payload, context = self.dialog.backend.submitted[-1]
        self.assertEqual(payload["action"], "generate")
        self.assertFalse(payload["record"]["coordinates_ready"])
        self.assertEqual(context["operation"], "generate")
        self.assertEqual(self.builds, [])

    def test_ready_coordinates_are_reused_when_style_changes(self):
        self.select(self.generated)
        self.dialog.SetInt32(self.ui.BOND_MODE, 1)
        self.dialog.SetInt32(self.ui.BOND_MATERIAL, 0)
        self.dialog.Command(self.ui.GENERATE, None)
        self.assertEqual(len(self.builds), 1)
        _, record, style, replacement = self.builds[0]
        self.assertEqual(record["atoms"], self.generated["atoms"])
        self.assertEqual(style["bond_mode"], "single")
        self.assertEqual(style["bond_material"], "uniform")
        self.assertIsNone(replacement)
        self.assertEqual(self.dialog.backend.submitted, [])

    def test_atom_color_does_not_change_bond_colors(self):
        original_bonds = copy.deepcopy(self.dialog.style["bond_element_colors"])
        original_unified = copy.deepcopy(self.dialog.style["bond_color"])
        self.dialog.SetInt32(self.ui.ELEMENT, 2)
        self.dialog.SetColorField(self.ui.ELEMENT_COLOR, self.ui.c4d.Vector(0.2, 0.3, 0.4))
        self.dialog.Command(self.ui.APPLY_COLOR, None)
        style = self.dialog._get_style()
        self.assertEqual(style["element_colors"]["O"], [0.2, 0.3, 0.4])
        self.assertEqual(style["bond_element_colors"], original_bonds)
        self.assertEqual(style["bond_color"], original_unified)

    def test_cancel_and_close_drop_late_generation_result(self):
        for close in (False, True):
            with self.subTest(close=close):
                self.select(self.source)
                self.dialog.Command(self.ui.GENERATE, None)
                token, _, context = self.dialog.backend.submitted[-1]
                if close:
                    self.dialog.DestroyWindow()
                else:
                    self.dialog.Command(self.ui.CANCEL, None)
                self.dialog.backend.finish({"ok": True, "record": self.generated}, token, context)
                self.dialog.Timer(None)
                self.assertEqual(self.builds, [])

    def test_document_switch_drops_late_generation_result(self):
        self.select(self.source)
        self.dialog.Command(self.ui.GENERATE, None)
        self.current_document["value"] = FakeDocument()
        self.dialog.backend.finish({"ok": True, "record": self.generated})
        self.dialog.Timer(None)
        self.assertEqual(self.builds, [])
        self.assertIn("场景已切换", self.dialog.GetString(self.ui.STATUS))

    def test_imported_favorite_requires_generation_even_with_3d_flag(self):
        self.dialog.library.save(self.generated, normalized_style(), "乙醇")
        export = Path(self.temp.name) / "favorites.json"
        self.dialog.library.export_to(export)
        imported = Library(Path(self.temp.name) / "imported")
        imported.import_from(export)
        self.dialog.library = imported
        self.dialog.SetBool(self.ui.FAVORITES, True)
        self.dialog.SetBool(self.ui.COMMON, False)
        self.dialog.Command(self.ui.FAVORITES, None)
        self.dialog._select(0)
        self.assertTrue(self.dialog._record()["has_3d"])
        self.assertFalse(self.dialog._record()["coordinates_ready"])
        self.dialog.Command(self.ui.GENERATE, None)
        _, payload, _ = self.dialog.backend.submitted[-1]
        self.assertEqual(payload["action"], "generate")
        self.assertEqual(self.builds, [])

    def test_switching_candidate_closes_selector_for_previous_model(self):
        self.use_fake_selector()
        self.dialog._show_records([self.generated], "model")
        self.dialog._select(0)
        self.dialog._open_atom_selector_ready()
        old_selector = self.dialog.atom_selector
        other = chemistry_worker.handle({"action": "resolve", "kind": "smiles",
                                         "text": "CO", "cache_dir": str(Path(self.temp.name) / "cache")})["records"][0]
        self.dialog._show_records([self.generated, other], "resolve")
        self.dialog._select(1)
        self.assertTrue(old_selector.closed)
        self.assertIsNone(self.dialog.atom_selector)
        self.assertIsNone(self.dialog.selector_root)

    def test_switching_legacy_candidates_without_integrity_closes_selector(self):
        self.use_fake_selector()
        first = copy.deepcopy(self.source)
        first.pop("record_integrity", None)
        other = chemistry_worker.handle({"action": "resolve", "kind": "smiles",
                                         "text": "CO", "cache_dir": str(Path(self.temp.name) / "cache")})["records"][0]
        other.pop("record_integrity", None)
        self.dialog._show_records([first, other], "resolve")
        self.dialog._select(0)
        self.dialog._open_atom_selector_ready()
        old_selector = self.dialog.atom_selector
        self.dialog._select(1)
        self.assertTrue(old_selector.closed)
        self.assertIsNone(self.dialog.atom_selector)

    def test_reopening_same_model_keeps_pending_selector_groups(self):
        self.use_fake_selector()
        root = FakeRoot(self.generated, normalized_style())
        self.document.active = root
        self.dialog._open_atom_selector()
        selector = self.dialog.atom_selector
        selector.groups = {"7": {"atom_ids": [0], "origin": [0, 0, 0],
                                 "normal": [0, 0, 1], "color": [1, 0, 0]}}
        self.dialog._open_atom_selector()
        self.assertIs(self.dialog.atom_selector, selector)
        self.assertFalse(selector.closed)
        self.assertEqual(selector.set_groups_calls, 1)
        self.assertEqual(selector.groups["7"]["atom_ids"], [0])

    def test_missing_thumbnail_file_requests_preview_despite_hotspots(self):
        record = copy.deepcopy(self.generated)
        self.assertTrue(record.get("thumbnail_atom_positions"))
        record["thumbnail"] = str(Path(self.temp.name) / "missing-preview.png")
        self.dialog._show_records([record], "resolve")
        self.dialog._select(0)
        _, payload, context = self.dialog.backend.submitted[-1]
        self.assertEqual(payload["action"], "preview")
        self.assertEqual(context["operation"], "preview")
        self.assertEqual(context["index"], 0)

    def test_common_and_favorites_are_independent_and_both_can_hide(self):
        self.dialog.builtins = [self.source]
        self.dialog.library.save(self.generated, normalized_style(), "乙醇")
        for common, favorites in ((True, False), (False, True), (True, True)):
            self.dialog.SetBool(self.ui.COMMON, common)
            self.dialog.SetBool(self.ui.FAVORITES, favorites)
            self.dialog.Command(self.ui.COMMON, None)
            self.dialog.Command(self.ui.FAVORITES, None)
            sources = {r["list_source"] for r in self.dialog.records}
            self.assertEqual(sources, ({"常用"} if common else set()) | ({"收藏"} if favorites else set()))
        self.dialog._select(0)
        chosen = self.dialog._record()["structure_key"]
        self.dialog.SetBool(self.ui.COMMON, False)
        self.dialog.SetBool(self.ui.FAVORITES, False)
        self.dialog.Command(self.ui.COMMON, None)
        self.dialog.Command(self.ui.FAVORITES, None)
        self.assertEqual(self.dialog.view, "library_hidden")
        self.assertEqual(self.dialog._record()["structure_key"], chosen)

    def test_only_successful_new_models_increment_usage(self):
        self.dialog._build(self.generated, normalized_style(), self.document)
        self.assertEqual(self.dialog.usage.ranked([])[0]["usage_count"], 1)
        self.dialog._build(self.generated, normalized_style(), self.document,
                           FakeRoot(self.generated, normalized_style()))
        self.assertEqual(self.dialog.usage.ranked([])[0]["usage_count"], 1)
        with patch.object(self.ui.c4d_builder, "build_model", side_effect=ValueError("拒绝更新")):
            with self.assertRaises(ValueError):
                self.dialog._build(self.generated, normalized_style(), self.document)
        self.assertEqual(self.dialog.usage.ranked([])[0]["usage_count"], 1)

    def test_reading_same_structure_copy_rebinds_editor_to_actual_root(self):
        self.use_fake_selector()
        first, second = [FakeRoot(self.generated, normalized_style()) for _ in range(2)]
        self.document.active = first
        self.dialog._open_atom_selector()
        old_selector = self.dialog.atom_selector
        self.dialog.SetBool(self.ui.EDIT_MODE, True)
        self.document.active = second
        self.dialog.Command(self.ui.READ_MODEL, None)
        self.assertIs(self.dialog.selector_root, second)
        self.assertTrue(old_selector.closed)
        self.assertIsNot(self.dialog.atom_selector, old_selector)

    def test_model_switch_preserves_draft_for_the_original_root(self):
        self.use_fake_selector()
        first, second = [FakeRoot(self.generated, normalized_style()) for _ in range(2)]
        self.document.active = first
        self.dialog._open_atom_selector()
        draft = {"1":{"atom_ids":[0,1],"origin":[0,0,0],"normal":[0,0,1],"color":[1,0,0]}}
        self.dialog.atom_selector.groups = copy.deepcopy(draft)
        self.dialog.atom_selector.groups_dirty = True
        self.dialog.SetBool(self.ui.EDIT_MODE, True)
        self.document.active = second
        self.dialog.Command(self.ui.READ_MODEL, None)
        self.assertEqual(self.dialog.atom_selector.groups, {})
        self.document.active = first
        self.dialog.Command(self.ui.READ_MODEL, None)
        self.assertIs(self.dialog.selector_root, first)
        self.assertEqual(self.dialog.atom_selector.groups, draft)
        self.assertTrue(self.dialog.atom_selector.groups_dirty)


if __name__ == "__main__":
    unittest.main()
