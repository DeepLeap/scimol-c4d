"""Contract tests for the resource browser without launching Cinema 4D."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class FakeArea:
    def __init__(self):
        self.width = 340
        self.height = 400
        self.draws = []
        self.tracking = False
        self.drag_packets = []

    def GetWidth(self):
        return self.width

    def GetHeight(self):
        return self.height

    def Global2Local(self):
        return {"x": 0, "y": 0}

    def MouseDragStart(self, *args):
        self.tracking = True

    def MouseDrag(self):
        return self.drag_packets.pop(0)

    def MouseDragEnd(self):
        self.tracking = False
        return 2

    def OffScreenOn(self):
        self.draws.append(("buffer",))

    def DrawSetPen(self, *args):
        self.draws.append(("pen", args))

    def DrawRectangle(self, *args):
        self.draws.append(("rectangle", args))

    def DrawSetTextCol(self, *args):
        self.draws.append(("text_color", args))

    def DrawText(self, *args):
        self.draws.append(("text", args))

    def GetColorRGB(self, _color):
        return {"r": 44, "g": 46, "b": 50}

    def Message(self, _msg, _result):
        return False

    def DrawBitmap(self, *args):
        self.draws.append(("bitmap", args))

    def DrawGetTextWidth(self, text):
        return len(text)*10

    def DrawGetFontHeight(self):
        return 15

    def DrawLine(self, *args):
        self.draws.append(("line", args))


class FakeBitmap:
    def InitWith(self, path):
        self.path = path
        return (1, False)

    def GetBw(self):
        return 200

    def GetBh(self):
        return 100


class Message:
    def __init__(self, channel, x=20, y=20):
        self.values = {1: 1, 2: 1, 3: channel, 4: x, 5: y}

    def GetInt32(self, key):
        return self.values[key]


class HoverMessage(Message):
    def GetId(self):
        return 77


class HoverResult:
    def __init__(self):
        self.values = {}

    def SetId(self, value):
        self.values["id"] = value

    def SetString(self, key, value):
        self.values[key] = value


class Owner:
    def __init__(self):
        self.folder_nodes = [
            {"id": "common", "name": "常用", "parent": None, "children": []},
            {"id": "favorites", "name": "收藏", "parent": None,
             "children": ["customcategory"]},
            {"id": "customcategory", "name": "自建文件夹", "parent": "favorites",
             "children": ["folder-1"]},
            {"id": "folder-1", "name": "芳香族", "parent": "customcategory",
             "children": []},
        ]
        self.folder_current = "common"
        self.records = []
        self.selected = -1
        self.calls = []

    def _browse_folder(self, folder_id):
        self.folder_current = folder_id
        self.calls.append(("folder", folder_id))

    def _select(self, index):
        self.selected = index
        self.calls.append(("select", index))

    def _resource_menu(self, index):
        self.calls.append(("menu", index))

    def _drag_asset(self, index, msg, area):
        assert not area.tracking
        self.calls.append(("drag", index))


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c4d = types.ModuleType("c4d")
        cls.c4d.gui = types.SimpleNamespace(TreeViewFunctions=type("TreeViewFunctions", (), {}),
                                             GeUserArea=FakeArea)
        cls.c4d.bitmaps = types.SimpleNamespace(BaseBitmap=FakeBitmap)
        cls.c4d.Vector = lambda *values: values
        cls.c4d.SELECTION_NEW = 10
        cls.c4d.SELECTION_SUB = 11
        cls.c4d.COLOR_TEXT = 12
        cls.c4d.COLOR_TEXT_SELECTED = 13
        cls.c4d.COLOR_BG = 14
        cls.c4d.COLOR_BG_GROUP1 = 15
        cls.c4d.COLOR_BORDER_ACTIVE_1 = 16
        cls.c4d.COLOR_BGSELECTEDTEXT = 17
        cls.c4d.IMAGERESULT_OK = 1
        cls.c4d.BMP_NORMALSCALED = 2
        cls.c4d.BMP_ALLOWALPHA = 4
        cls.c4d.BFM_INPUT_DEVICE = 1
        cls.c4d.BFM_INPUT_VALUE = 2
        cls.c4d.BFM_INPUT_CHANNEL = 3
        cls.c4d.BFM_INPUT_X = 4
        cls.c4d.BFM_INPUT_Y = 5
        cls.c4d.BFM_INPUT_MOUSE = 1
        cls.c4d.BFM_GETCURSORINFO = 77
        cls.c4d.RESULT_BUBBLEHELP = 78
        cls.c4d.BFM_INPUT_MOUSELEFT = 6
        cls.c4d.BFM_INPUT_MOUSERIGHT = 7
        cls.c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE = 8
        cls.c4d.MOUSEDRAGRESULT_CONTINUE = 1
        cls.c4d.MOUSEDRAGRESULT_FINISHED = 2
        cls.c4d.MOUSEDRAGRESULT_ESCAPE = 3
        cls.stub = patch.dict(sys.modules, {"c4d": cls.c4d})
        cls.stub.start()
        spec = importlib.util.spec_from_file_location("resource_browser_under_test",
                                                   ROOT / "scimol_c4d" / "resource_browser.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.stub.stop()

    def test_folder_tree_navigates_nested_categories_and_selects_one(self):
        owner = Owner()
        tree = self.module.FolderFunctions(owner)
        common = tree.GetFirst(None, None)
        favorites = tree.GetNext(None, None, common)
        category = tree.GetDown(None, None, favorites)
        child = tree.GetDown(None, None, category)
        self.assertEqual((common["id"], favorites["id"], category["id"], child["id"]),
                         ("common", "favorites", "customcategory", "folder-1"))
        self.assertIsNone(tree.GetNext(None, None, favorites))
        self.assertEqual(tree.GetPred(None, None, favorites)["id"], "common")
        self.assertEqual(len({tree.GetId(None, None, node) for node in owner.folder_nodes}), 4)
        tree.Select(None, None, child, self.c4d.SELECTION_NEW)
        self.assertEqual(owner.calls, [("folder", "folder-1")])
        self.assertTrue(tree.IsSelected(None, None, child))
        tree.Select(None, None, common, self.c4d.SELECTION_SUB)
        self.assertEqual(owner.folder_current, "folder-1")

    def test_user_tree_cell_draws_folder_name_with_selection_color(self):
        owner = Owner()
        tree = self.module.FolderFunctions(owner)
        area = FakeArea()
        obj = owner.folder_nodes[0]
        self.assertEqual(tree.GetColumnWidth(None, None, obj, 0, area), 50)
        info = {"frame": area, "xpos": 5, "ypos": 10, "height": 25}
        self.assertEqual(tree.DrawCell(None, None, obj, 0, info, 99), 99)
        self.assertTrue(any(item[0] == "line" for item in area.draws))
        owner.folder_current = "favorites"
        colors = []
        area.DrawSetTextCol = lambda foreground, background: colors.append((foreground, background))
        tree.DrawCell(None, None, owner.folder_nodes[1], 0, info, 99)
        self.assertEqual(colors[-1], (self.c4d.COLOR_TEXT_SELECTED, 99))

    def test_empty_grid_height_and_responsive_hit_testing(self):
        owner = Owner()
        area = self.module.ThumbnailArea(owner)
        self.assertGreaterEqual(area.GetMinSize()[1], 360)
        owner.records = [{"name": str(i)} for i in range(8)]
        self.assertEqual(area._columns(), 3)
        self.assertEqual(area._hit(20, 20), 0)
        self.assertEqual(area._hit(128, 20), 1)
        self.assertIsNone(area._hit(110, 20))
        area.width = 130
        self.assertEqual(area._columns(), 1)
        self.assertEqual(area._hit(20, 122), 1)
        self.assertGreaterEqual(area.GetMinSize()[1], 8*114)

    def test_click_menu_and_marquee_end_without_scene_drag(self):
        owner = Owner()
        owner.records = [{"name": "苯"}]
        area = self.module.ThumbnailArea(owner)
        area.drag_packets = [(2, 0.0, 0.0, None)]
        self.assertTrue(area.InputEvent(Message(self.c4d.BFM_INPUT_MOUSELEFT)))
        self.assertEqual(owner.calls, [("select", 0)])
        self.assertTrue(area.InputEvent(Message(self.c4d.BFM_INPUT_MOUSERIGHT)))
        self.assertEqual(owner.calls[-1], ("menu", 0))
        prior = owner.calls[:]
        area.drag_packets = [(1, 3.0, 0.0, None), (1, 3.0, 0.0, None), (2, 0., 0., None)]
        self.assertTrue(area.InputEvent(Message(self.c4d.BFM_INPUT_MOUSELEFT)))
        self.assertEqual(owner.calls, prior)
        prior = owner.calls[:]
        area.drag_packets = [(3, 0.0, 0.0, None)]
        self.assertTrue(area.InputEvent(Message(self.c4d.BFM_INPUT_MOUSELEFT)))
        self.assertEqual(owner.calls, prior)

    def test_bitmap_is_contained_without_cropping(self):
        owner = Owner()
        icon = ROOT / "assets" / "benzene_ball_stick.png"
        owner.records = [{"name": "示意", "transparent_dark_thumbnail": str(icon)}]
        area = self.module.ThumbnailArea(owner)
        area.DrawMsg(0, 0, 340, 400, None)
        self.assertEqual(area.draws[0], ("buffer",))
        draw = next(item[1] for item in area.draws if item[0] == "bitmap")
        self.assertEqual(draw[5:9], (0, 0, 200, 100))
        self.assertAlmostEqual(draw[3]/draw[4], 2.0, delta=0.05)

    def test_native_background_transparent_ink_and_no_white_fallback(self):
        owner = Owner()
        fallback = ROOT / "assets" / "benzene_ball_stick.png"
        transparent = ROOT / "assets" / "benzene_space_fill.png"
        owner.records = [{"name": "苯", "thumbnail": str(fallback),
                          "transparent_dark_thumbnail": str(transparent)}]
        owner.selected = 0
        area = self.module.ThumbnailArea(owner)
        area.DrawMsg(0, 0, 340, 400, None)
        pens = [item[1][0] for item in area.draws if item[0] == "pen"]
        self.assertEqual(pens[:3], [self.c4d.COLOR_BG,
                                     self.c4d.COLOR_BGSELECTEDTEXT,
                                     self.c4d.COLOR_BG])
        draw = next(item[1] for item in area.draws if item[0] == "bitmap")
        self.assertEqual(draw[0].path, str(transparent))
        self.assertIn(("text_color", (self.c4d.COLOR_TEXT,
                                       self.c4d.COLOR_BG)), area.draws)
        owner.records[0]["transparent_dark_thumbnail"] = str(ROOT / "assets" / "missing.png")
        area.draws.clear()
        area.DrawMsg(0, 0, 340, 400, None)
        self.assertFalse(any(item[0] == "bitmap" for item in area.draws))

    def test_card_name_centers_and_hover_exposes_full_name(self):
        owner = Owner()
        owner.records = [{"name": "非常长的化学结构名称ABC"}]
        area = self.module.ThumbnailArea(owner)
        area.DrawMsg(0, 0, 340, 400, None)
        name, x, y = next(item[1] for item in area.draws if item[0] == "text")
        self.assertEqual(name, "非常长的化学结构名…")
        self.assertEqual(x, area.MARGIN + max(5, (area.CARD_WIDTH - len(name)*10)//2))
        self.assertEqual(y, area.MARGIN + 83)
        result = HoverResult()
        self.assertTrue(area.Message(HoverMessage(self.c4d.BFM_INPUT_MOUSELEFT), result))
        self.assertEqual(result.values[self.c4d.RESULT_BUBBLEHELP],
                         owner.records[0]["name"])
        blank = HoverResult()
        self.assertFalse(area.Message(HoverMessage(self.c4d.BFM_INPUT_MOUSELEFT, 200, 200),
                                      blank))
        self.assertEqual(blank.values, {})

    def test_action_icons_are_transparent_light_gray(self):
        names = ("search", "confirm", "sidebar_left", "sidebar_right",
                 "import", "folder_add", "favorite_add", "more")
        for name in names:
            with self.subTest(name=name), Image.open(ROOT / "assets" / (name + ".png")) as image:
                self.assertEqual(image.size, (64, 64))
                self.assertEqual(image.mode, "RGBA")
                raw = image.tobytes()
                pixels = [tuple(raw[i:i+4]) for i in range(0, len(raw), 4)]
                self.assertTrue(any(alpha == 0 for _, _, _, alpha in pixels))
                strokes = [(red, green, blue) for red, green, blue, alpha in pixels if alpha]
                self.assertTrue(strokes)
                self.assertTrue(all(205 <= channel <= 220 for rgb in strokes
                                    for channel in rgb))


if __name__ == "__main__":
    unittest.main()
