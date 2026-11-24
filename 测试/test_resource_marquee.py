"""Portable selection contracts for the native thumbnail area (no C4D host)."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "scimol_c4d" / "resource_browser.py"


class AreaBase:
    def __init__(self):
        self.width = 340
        self.height = 400
        self.drag_packets = []
        self.dragging = False
        self.redraws = 0
        self.draws = []

    def GetWidth(self):
        return self.width

    def GetHeight(self):
        return self.height

    def Global2Local(self):
        return {"x": 0, "y": 0}

    def MouseDragStart(self, *_args):
        self.dragging = True

    def MouseDrag(self):
        return self.drag_packets.pop(0)

    def MouseDragEnd(self):
        self.dragging = False
        return 2

    def Redraw(self):
        self.redraws += 1

    def OffScreenOn(self):
        self.draws.append(("offscreen",))

    def GetColorRGB(self, _color):
        return {"r": 40, "g": 40, "b": 40}

    def DrawSetPen(self, color):
        self.draws.append(("pen", color))

    def DrawRectangle(self, *box):
        self.draws.append(("rectangle", box))

    def DrawLine(self, *line):
        self.draws.append(("line", line))

    def DrawSetTextCol(self, *colors):
        self.draws.append(("text_color", colors))

    def DrawGetTextWidth(self, text):
        return len(text)*8

    def DrawText(self, *args):
        self.draws.append(("text", args))


class Event:
    def __init__(self, x, y, qualifier=0, channel=6):
        self.values = {1: 1, 2: 1, 3: channel, 4: x, 5: y, 9: qualifier}

    def GetInt32(self, key):
        return self.values[key]


class Owner:
    def __init__(self):
        self.records = [{"name": str(index)} for index in range(8)]
        self.selected = -1
        self.selected_cards = set()
        self.calls = []

    def _select(self, index):
        self.selected = index
        self.selected_cards = {index}  # Main controller's single-active convention.
        self.calls.append(("select", index))

    def _drag_asset(self, index, _msg, area):
        assert not area.dragging
        self.calls.append(("drag", index))


class MarqueeTests(unittest.TestCase):
    def test_rejected_plain_click_keeps_selection_but_ctrl_add_still_works(self):
        owner=Owner()
        owner.selected=0
        owner.selected_cards={0}
        owner.current_record={'name':'0'}
        owner._select=lambda index: False
        area=self.module.ThumbnailArea(owner)
        area._anchor=0
        area._click_card(1)
        self.assertEqual(owner.selected_cards,{0})
        self.assertEqual(area._anchor,0)
        area._click_card(1,ctrl=True)
        self.assertEqual(owner.selected_cards,{0,1})
        self.assertEqual(owner.selected,0)

    @classmethod
    def setUpClass(cls):
        cls.c4d = types.ModuleType("c4d")
        cls.c4d.gui = types.SimpleNamespace(
            TreeViewFunctions=type("Tree", (), {}), GeUserArea=AreaBase)
        constants = {
            "BFM_INPUT_DEVICE": 1, "BFM_INPUT_VALUE": 2,
            "BFM_INPUT_CHANNEL": 3, "BFM_INPUT_X": 4, "BFM_INPUT_Y": 5,
            "BFM_INPUT_MOUSE": 1, "BFM_INPUT_MOUSELEFT": 6,
            "BFM_INPUT_MOUSERIGHT": 7, "BFM_INPUT_QUALIFIER": 9,
            "QUALIFIER_SHIFT": 1, "QUALIFIER_CTRL": 2,
            "MOUSEDRAGFLAGS_DONTHIDEMOUSE": 8,
            "MOUSEDRAGRESULT_CONTINUE": 1,
            "MOUSEDRAGRESULT_FINISHED": 2,
            "MOUSEDRAGRESULT_ESCAPE": 3,
            "COLOR_BG": 20, "COLOR_TEXT": 21,
            "COLOR_TEXT_SELECTED": 22, "COLOR_BGSELECTEDTEXT": 23,
            "COLOR_ICONS_BG_ACTIVE": 24, "COLOR_BORDER_ACTIVE_1": 25,
        }
        for name, value in constants.items():
            setattr(cls.c4d, name, value)
        cls.patch = patch.dict(sys.modules, {"c4d": cls.c4d})
        cls.patch.start()
        spec = importlib.util.spec_from_file_location("resource_marquee_under_test", SOURCE)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()

    def setUp(self):
        self.owner = Owner()
        self.area = self.module.ThumbnailArea(self.owner)

    def click(self, index, qualifier=0):
        x, y = self.area._card_box(index)
        self.area.drag_packets = [(2, 0, 0, None)]
        self.assertTrue(self.area.InputEvent(Event(x+5, y+5, qualifier)))

    def frame(self, start, packets, qualifier=0):
        self.area.drag_packets = packets
        self.assertTrue(self.area.InputEvent(Event(*start, qualifier)))

    def test_click_ctrl_toggle_shift_range_and_ctrl_shift_union(self):
        self.click(0)
        self.click(2, 2)
        self.assertEqual(self.owner.selected_cards, {0, 2})
        self.click(4, 1)
        self.assertEqual(self.owner.selected_cards, {2, 3, 4})
        self.assertEqual(self.owner.selected, 0)
        self.click(1, 3)
        self.assertEqual(self.owner.selected_cards, {1, 2, 3, 4})
        self.click(2, 2)
        self.assertEqual(self.owner.selected_cards, {1, 3, 4})
        self.assertEqual(self.owner.calls, [("select", 0)])

    def test_card_intersection_is_direction_independent_and_excludes_gaps(self):
        for corners in ((5, 5, 225, 115), (225, 115, 5, 5),
                        (5, 115, 225, 5), (225, 5, 5, 115)):
            self.assertEqual(self.area._cards_in_box(*corners), {0, 1, 2})
        self.assertEqual(self.area._cards_in_box(109, 8, 115, 113), set())
        self.area.width = 130
        self.assertEqual(self.area._cards_in_box(5, 120, 110, 225), {1})

    def test_marquee_native_delta_sign_modifiers_and_active_preview(self):
        # Start in the horizontal/vertical gap, move left/up to cover card zero.
        start = (115, 120)
        self.frame(start, [(1, 95, 100, None), (2, 0, 0, None)])
        self.assertEqual(self.owner.selected_cards, {0})
        self.assertEqual(self.owner.selected, 0)
        self.owner.selected_cards = {2}
        self.frame(start, [(1, 95, 100, None), (2, 0, 0, None)], 1)
        self.assertEqual(self.owner.selected_cards, {0, 2})
        self.assertEqual(self.owner.selected, 0)
        self.frame(start, [(1, 95, 100, None), (2, 0, 0, None)], 2)
        self.assertEqual(self.owner.selected_cards, {2})
        self.assertIsNone(self.area._marquee)
        self.assertGreater(self.area.redraws, 0)

    def test_multi_selection_keeps_bound_record_even_when_selected_index_invalid(self):
        self.owner.current_record = {"name": "已绑定的独立结构"}
        self.click(1, 2)
        self.assertEqual(self.owner.selected_cards, {1})
        self.assertEqual(self.owner.selected, -1)
        self.assertEqual(self.owner.calls, [])
        self.click(3)
        self.assertEqual(self.owner.selected, 3)
        self.assertEqual(self.owner.selected_cards, {3})

    def test_empty_click_keeps_binding_and_escape_keeps_selection(self):
        self.click(1)
        self.frame((330, 300), [(2, 0, 0, None)])
        self.assertEqual(self.owner.selected_cards, set())
        self.assertEqual(self.owner.selected, 1)
        self.click(1)
        old_calls = list(self.owner.calls)
        self.frame((115, 120), [(1, 95, 100, None), (3, 0, 0, None)])
        self.assertEqual(self.owner.selected_cards, {1})
        self.assertEqual(self.owner.calls, old_calls)
        self.assertIsNone(self.area._marquee)

    def test_card_drag_selects_resources_without_generating_scene_asset(self):
        self.click(0)
        self.click(1, 2)
        calls=list(self.owner.calls)
        self.area.drag_packets = [(1, -6, 0, None),(2,0,0,None)]
        self.area.InputEvent(Event(20, 20))
        self.assertEqual(self.owner.calls,calls)
        self.assertEqual(self.owner.selected_cards, {0})
        self.area.DrawMsg(0, 0, 340, 400, None)
        self.assertIn(("pen", self.c4d.COLOR_ICONS_BG_ACTIVE), self.area.draws)
        self.assertIn(("text_color", (self.c4d.COLOR_TEXT_SELECTED,
                                      self.c4d.COLOR_ICONS_BG_ACTIVE)), self.area.draws)

    def test_empty_search_area_displays_loading_instead_of_empty_folder(self):
        self.owner.records=[]
        self.owner.folder_current='search'
        self.owner.search_pending=True
        self.owner.search_message='正在搜索...'
        self.area.DrawMsg(0,0,340,400,None)
        self.assertIn(('text',('正在搜索...',12,18)),self.area.draws)
        self.assertNotIn(('text',('此文件夹暂无结构',12,18)),self.area.draws)


if __name__ == "__main__":
    unittest.main()
