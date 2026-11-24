"""Old 2D images refresh locally without changing molecule or editor state."""

import copy
import unittest

from scimol_c4d.records import DEPICTION_VERSION, record_integrity
from 测试 import test_browser_states as _states
Editor = _states.Editor


class DepictionRefreshTests(unittest.TestCase):
    setUp = _states.BrowserStateTests.setUp

    @classmethod
    def setUpClass(cls):
        _states.BrowserStateTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        _states.BrowserStateTests.tearDownClass.__func__(cls)

    def test_version_controls_preview_validity_and_cached_search_stays_local(self):
        dialog = self.dialog
        old = copy.deepcopy(self.source)
        old.pop("depiction_version", None)
        self.assertFalse(dialog._has_theme(old))
        self.assertFalse(dialog._has_atom_preview(old))
        dialog._resolve_cache["CCO"] = [old]
        dialog._search("CCO")
        self.assertEqual(dialog.backend.submitted, [])
        self.assertEqual(dialog.preview_backend.submitted[-1][1]["action"], "previews")
        self.assertIn("CCO", dialog._resolve_cache)

    def test_batch_refresh_updates_editor_and_session_caches_by_integrity(self):
        dialog = self.dialog
        old = copy.deepcopy(self.ready)
        old.pop("depiction_version", None)
        dialog.editor = Editor()
        dialog.editor.groups_dirty = True
        dialog.editor.selected_ids = {0}
        dialog.records = [copy.deepcopy(old)]
        dialog.builtins = [copy.deepcopy(old)]
        dialog.search_records = [copy.deepcopy(old)]
        dialog._resolve_cache["CCO"] = [copy.deepcopy(old)]
        key = record_integrity(old)
        dialog._ready_records[key] = copy.deepcopy(old)
        dialog._display(old)
        refreshed = copy.deepcopy(old)
        refreshed["depiction_version"] = DEPICTION_VERSION
        refreshed["thumbnail_atom_positions"] = {"0": [123, 45]}
        dialog._remember_previews([refreshed])
        for record in (dialog.records[0], dialog.builtins[0],
                       dialog.search_records[0], dialog._resolve_cache["CCO"][0],
                       dialog._ready_records[key], dialog.current_record,
                       dialog.editor._record):
            self.assertEqual(record["depiction_version"], DEPICTION_VERSION)
            self.assertEqual(record["thumbnail_atom_positions"], {"0": [123, 45]})
            self.assertEqual(record_integrity(record), key)
        self.assertTrue(dialog.editor.groups_dirty)
        self.assertEqual(dialog.editor.selected_ids, {0})
        self.assertTrue(dialog.current_record["coordinates_ready"])
        self.assertTrue(dialog._has_theme(dialog._cached_preview(old)))

    def test_same_smiles_with_different_atom_order_does_not_receive_preview(self):
        dialog = self.dialog
        source = copy.deepcopy(self.source)
        other = copy.deepcopy(source)
        other["atoms"][0]["element"], other["atoms"][2]["element"] = (
            other["atoms"][2]["element"], other["atoms"][0]["element"])
        other["record_integrity"] = record_integrity(other)
        self.assertEqual(source["structure_key"], other["structure_key"])
        self.assertNotEqual(record_integrity(source), record_integrity(other))
        dialog.records = [other]
        refreshed = copy.deepcopy(source)
        refreshed["depiction_version"] = DEPICTION_VERSION
        refreshed["thumbnail_atom_positions"] = {"0": [123, 45]}
        dialog._remember_previews([refreshed])
        self.assertNotEqual(dialog.records[0]["thumbnail_atom_positions"], {"0": [123, 45]})
        dialog.current_record = copy.deepcopy(other)
        dialog._start({"action": "preview", "record": source}, "preview",
                      structure_key=source["structure_key"])
        context = dialog.preview_backend.submitted[-1][2]
        dialog._accept_result(context, {"ok": True, "record": refreshed})
        self.assertEqual(dialog.current_record, other)

    def test_batch_result_from_previous_folder_is_reused_in_new_folder(self):
        dialog = self.dialog
        old = copy.deepcopy(self.source)
        old.pop("depiction_version", None)
        dialog.records = [copy.deepcopy(old)]
        dialog.view = "common"
        dialog._refresh_missing_previews()
        context = dialog.preview_backend.submitted[-1][2]
        dialog.view = "favorites"
        dialog.records = [copy.deepcopy(old)]
        refreshed = copy.deepcopy(old)
        refreshed["depiction_version"] = DEPICTION_VERSION
        dialog._preview_pending = False
        dialog._accept_result(context, {"ok": True, "records": [refreshed]})
        self.assertEqual(dialog.records[0]["depiction_version"], DEPICTION_VERSION)
        self.assertEqual(dialog.preview_backend.submitted[-1][2], context)


if __name__ == "__main__":
    unittest.main()
