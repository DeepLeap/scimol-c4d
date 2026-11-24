"""Native, image-backed selection of visible atoms and bonds."""

import math
import os
import copy

import c4d

from .native_ui import add_action, add_brand_logo, add_icon, hover_help
from .records import record_integrity
from .appearance_scale import to_display, to_physical, display_limits
from .display_geometry import ring_center_options


IMAGE = 2101
COUNT = 2102
SELECT_ALL = 2103
CLEAR = 2104
PLANE = 2105
FLATTEN = 2106
RESTORE = 2107
STATUS = 2108
SHOW_GROUPS = 2109
EDIT_CONTROLS = 2115
ALL_FLATTEN = 2113
BACKGROUND_WHITE = 2116
BACKGROUND_SLIDER = 2117
LOCAL_ATOM_RADIUS = 2120
LOCAL_ATOM_SLIDER = 2121
LOCAL_BOND_RADIUS = 2122
LOCAL_BOND_SLIDER = 2123
LOCAL_ATOM_NOTE = 2124
LOCAL_BOND_NOTE = 2125
LOCAL_RESET = 2126
SET_CENTER = 2134
RING_CENTER = 2135
RESET_CENTER = 2136
BACKGROUND_RESET = 2150
LOCAL_ATOM_RESET = 2151
LOCAL_BOND_RESET = 2152
SELECT_RING = 2155
INVERT_SELECT = 2156

ATOM_HIT_RADIUS = 14.0
BOND_HIT_RADIUS = 8.0
BOND_ENDPOINT_CLEARANCE = 14.0

ORIENTATIONS = ("original", "auto", "xy", "xz", "yz")
GROUP_COLORS = ((0.92, 0.25, 0.18), (0.13, 0.52, 0.92),
                (0.17, 0.68, 0.35), (0.72, 0.35, 0.87),
                (0.95, 0.60, 0.12), (0.10, 0.67, 0.70))


def _graph_key(record):
    """Ignore preview and style changes, which do not change atom identity."""
    atoms = record.get("atoms") or []
    return (record_integrity(record), record.get("smiles"), tuple(
        (atom.get("id"), atom.get("element")) for atom in atoms
        if isinstance(atom, dict)))


def _background_color(native_rgb, white_percent):
    """Blend a live C4D UI color with white; return a drawing color in 0..1."""
    amount = max(0.0, min(1.0, float(white_percent) / 100.0))
    return c4d.Vector(*(min(255, max(0, native_rgb[key])) / 255.0 * (1.0 - amount) + amount
                        for key in ("r", "g", "b")))


def _bond_key(a, b):
    return "%d:%d" % (min(a, b), max(a, b))


class _AtomImage(c4d.gui.GeUserArea):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.bitmap = None
        self.dark_bitmap = None
        self.light_bitmap = None
        self.source_size = (360, 280)
        self.positions = {}
        self.bonds = {}
        self.drag_box = None
        self.last_drag = None
        self.hover_atom = None
        self.hover_bond = None

    def GetMinSize(self):
        return (240, 190)

    def _image_box(self):
        width, height = max(1, self.GetWidth()), max(1, self.GetHeight())
        source_w, source_h = self.source_size
        scale = min(width / source_w, height / source_h)
        drawn_w = max(1, int(round(source_w * scale)))
        drawn_h = max(1, int(round(source_h * scale)))
        return ((width - drawn_w) // 2, (height - drawn_h) // 2,
                drawn_w, drawn_h)

    def DrawMsg(self, x1, y1, x2, y2, msg):
        self.OffScreenOn()
        self.SetClippingRegion(0, 0, self.GetWidth() - 1, self.GetHeight() - 1)
        self.DrawSetOpacity(1.0)
        whiteness = self.owner.background_white / 100.0
        native_rgb = self.GetColorRGB(c4d.COLOR_BG)
        self.DrawSetPen(_background_color(native_rgb, self.owner.background_white))
        self.DrawRectangle(0, 0, self.GetWidth(), self.GetHeight())
        left, top, width, height = self._image_box()
        # Both PNGs use exactly the same RDKit coordinates. Pick contrasting
        # ink as the backdrop brightens. Blending light and dark ink together
        # would make bonds disappear in the middle of the slider range.
        if self.light_bitmap is not None and self.dark_bitmap is not None:
            native_luma = (native_rgb["r"] + native_rgb["g"] + native_rgb["b"]) / 765.0
            backdrop_luma = native_luma * (1.0 - whiteness) + whiteness
            bitmap = self.dark_bitmap if backdrop_luma >= 0.5 else self.light_bitmap
            self.DrawBitmap(bitmap, left, top, width, height,
                            0, 0, bitmap.GetBw(), bitmap.GetBh(),
                            c4d.BMP_NORMALSCALED | c4d.BMP_ALLOWALPHA)
        elif self.bitmap is not None:
            # Pre-existing records can lack transparent previews until the
            # sidecar refreshes them; retain a readable diagram meanwhile.
            self.DrawBitmap(self.bitmap, left, top, width, height,
                            0, 0, self.bitmap.GetBw(), self.bitmap.GetBh(),
                            c4d.BMP_NORMALSCALED)
        source_w, source_h = self.source_size
        if self.owner.editing:
            self.DrawSetPen(c4d.Vector(0.98, 0.35, 0.04))
            for key in self.owner.selected_bonds:
                endpoints = self.bonds.get(key)
                if endpoints is None:
                    continue
                a, b = (self.positions[atom_id] for atom_id in endpoints)
                self.DrawLine(int(left + a[0] * width / source_w),
                              int(top + a[1] * height / source_h),
                              int(left + b[0] * width / source_w),
                              int(top + b[1] * height / source_h))
        if self.owner.show_groups:
            for group_id in sorted(self.owner.groups, key=int):
                group = self.owner.groups[group_id]
                members = [self.positions[atom_id] for atom_id in group["atom_ids"]
                           if atom_id in self.positions]
                if not members:
                    continue
                points = [(left + point[0] * width / source_w,
                           top + point[1] * height / source_h) for point in members]
                self.DrawSetPen(c4d.Vector(*group["color"]))
                self.DrawSetOpacity(0.13)
                if len(points) == 1:
                    self.DrawEllipseFill(list(points[0]), [14.0, 14.0])
                else:
                    low_x = max(left, min(point[0] for point in points) - 12)
                    high_x = min(left + width - 1, max(point[0] for point in points) + 12)
                    low_y = max(top, min(point[1] for point in points) - 12)
                    high_y = min(top + height - 1, max(point[1] for point in points) + 12)
                    self.DrawRoundedRectangle(int(low_x), int(low_y), int(high_x),
                                              int(high_y), 12.0, 12.0)
                self.DrawSetOpacity(1.0)
        self.DrawSetPen(c4d.Vector(0.98, 0.35, 0.04))
        for atom_id in self.owner.selected_ids if self.owner.editing else ():
            point = self.positions.get(atom_id)
            if point is None:
                continue
            px = left + point[0] * width / source_w
            py = top + point[1] * height / source_h
            self.DrawEllipseLine([px, py], [11.0, 11.0], 2.5)
        if self.owner.editing:
            if (self.hover_bond is not None and
                    self.hover_bond not in self.owner.selected_bonds and
                    self.hover_bond in self.bonds):
                a, b = (self.positions[atom_id] for atom_id in self.bonds[self.hover_bond])
                self.DrawSetPen(c4d.Vector(0.22, 0.72, 0.96))
                self.DrawLine(int(left + a[0] * width / source_w),
                              int(top + a[1] * height / source_h),
                              int(left + b[0] * width / source_w),
                              int(top + b[1] * height / source_h))
            if (self.hover_atom is not None and
                    self.hover_atom not in self.owner.selected_ids and
                    self.hover_atom in self.positions):
                point = self.positions[self.hover_atom]
                self.DrawSetPen(c4d.Vector(0.22, 0.72, 0.96))
                self.DrawEllipseLine([left + point[0] * width / source_w,
                                      top + point[1] * height / source_h],
                                     [12.0, 12.0], 2.0)
        if self.drag_box is not None and self.owner.editing:
            ax, ay, bx, by = self.drag_box
            self.DrawSetPen(c4d.Vector(0.1, 0.45, 0.9))
            self.DrawFrame(int(min(ax, bx)), int(min(ay, by)),
                           int(max(ax, bx)), int(max(ay, by)), 1.5)
        return True

    def _hit(self, x, y):
        left, top, width, height = self._image_box()
        if not (left <= x < left + width and top <= y < top + height):
            return None
        source_w, source_h = self.source_size
        closest_id, closest_distance = None, ATOM_HIT_RADIUS ** 2
        for atom_id, (pixel_x, pixel_y) in self.positions.items():
            hotspot_x = left + pixel_x * width / source_w
            hotspot_y = top + pixel_y * height / source_h
            distance = (x - hotspot_x) ** 2 + (y - hotspot_y) ** 2
            if distance <= closest_distance:
                closest_id, closest_distance = atom_id, distance
        return closest_id

    def _hit_bond(self, x, y):
        """Hit a visible bond near its centre, away from atom hotspots."""
        left, top, width, height = self._image_box()
        if not (left <= x < left + width and top <= y < top + height):
            return None
        source_w, source_h = self.source_size
        closest_key, closest_distance = None, BOND_HIT_RADIUS ** 2
        for key, (a_id, b_id) in self.bonds.items():
            a, b = self.positions[a_id], self.positions[b_id]
            ax, ay = left + a[0] * width / source_w, top + a[1] * height / source_h
            bx, by = left + b[0] * width / source_w, top + b[1] * height / source_h
            vx, vy = bx - ax, by - ay
            length_sq = vx * vx + vy * vy
            if length_sq == 0:
                continue
            t = ((x - ax) * vx + (y - ay) * vy) / length_sq
            clearance = min(BOND_ENDPOINT_CLEARANCE / math.sqrt(length_sq), 0.25)
            if not clearance <= t <= 1.0 - clearance:
                continue
            distance = (x - ax - t * vx) ** 2 + (y - ay - t * vy) ** 2
            if distance <= closest_distance:
                closest_key, closest_distance = key, distance
        return closest_key

    def _qualifiers(self, msg):
        key = getattr(c4d, "BFM_INPUT_QUALIFIER", None)
        try:
            mask = msg.GetInt32(key) if key is not None else 0
        except (KeyError, TypeError, AttributeError):
            mask = 0
        return (bool(mask & getattr(c4d, "QUALIFIER_SHIFT", 0)),
                bool(mask & getattr(c4d, "QUALIFIER_CTRL", 0)))

    def Message(self, msg, result):
        if msg.GetId() == c4d.BFM_GETCURSORINFO:
            tip = "左键点选可见原子或键，拖框选择（支持 Shift 加选 / Ctrl 增减）；隐式氢没有热点。右键为所选原子设置平面组。"
            if self.owner.editing:
                offset = self.Global2Local() if hasattr(self, "Global2Local") else None
                if offset is not None:
                    try:
                        x = msg.GetInt32(c4d.BFM_INPUT_X) + offset["x"]
                        y = msg.GetInt32(c4d.BFM_INPUT_Y) + offset["y"]
                    except (KeyError, TypeError, AttributeError):
                        x = y = None
                    if x is not None and y is not None:
                        atom_id = self._hit(x, y)
                        bond_key = None if atom_id is not None else self._hit_bond(x, y)
                        if (atom_id, bond_key) != (self.hover_atom, self.hover_bond):
                            self.hover_atom = atom_id
                            self.hover_bond = bond_key
                            if hasattr(self, "Redraw"):
                                self.Redraw()
                        if atom_id is not None and hasattr(self.owner, "_describe_atom"):
                            tip = self.owner._describe_atom(atom_id)
                        elif bond_key is not None and hasattr(self.owner, "_describe_bond"):
                            tip = self.owner._describe_bond(bond_key)
            result.SetId(c4d.BFM_GETCURSORINFO)
            result.SetString(c4d.RESULT_BUBBLEHELP, tip)
            result.SetInt32(c4d.RESULT_CURSOR, c4d.MOUSE_SELECT_RECT)
            return True
        return super().Message(msg, result)

    def InputEvent(self, msg):
        if not self.owner.editing:
            return False
        if (msg.GetInt32(c4d.BFM_INPUT_DEVICE) != c4d.BFM_INPUT_MOUSE or
                msg.GetInt32(c4d.BFM_INPUT_CHANNEL) not in
                (c4d.BFM_INPUT_MOUSELEFT, c4d.BFM_INPUT_MOUSERIGHT) or
                not msg.GetInt32(c4d.BFM_INPUT_VALUE)):
            return False
        # Input positions are window global; convert to this user area's space.
        offset = self.Global2Local()
        if offset is None:
            return False
        x = msg.GetInt32(c4d.BFM_INPUT_X) + offset["x"]
        y = msg.GetInt32(c4d.BFM_INPUT_Y) + offset["y"]
        if msg.GetInt32(c4d.BFM_INPUT_CHANNEL) == c4d.BFM_INPUT_MOUSERIGHT:
            atom_id = self._hit(x, y)
            if atom_id is not None and atom_id not in self.owner.selected_ids:
                self.owner.selected_ids = {atom_id}
                self.owner.selected_bonds.clear()
                self.owner._selection_changed()
            self.owner._show_group_menu()
            return True

        shift, ctrl = self._qualifiers(msg)
        self.MouseDragStart(c4d.BFM_INPUT_MOUSELEFT,
                            float(x), float(y),
                            c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE)
        end_x, end_y = float(x), float(y)
        self.last_drag = {"start": [x, y], "packets": [], "end": [x, y]}
        result = None
        try:
            while True:
                result, dx, dy, _channels = self.MouseDrag()
                if result != c4d.MOUSEDRAGRESULT_CONTINUE:
                    break
                # GeUserArea reports previous minus current mouse position.
                # A right/down movement therefore returns negative deltas.
                # See Maxon's marquee example: forum/topic/16267.
                end_x -= dx
                end_y -= dy
                if len(self.last_drag["packets"]) < 16:
                    self.last_drag["packets"].append([dx, dy])
                self.last_drag["end"] = [end_x, end_y]
                self.drag_box = (x, y, end_x, end_y)
                self.Redraw()
        finally:
            ended = self.MouseDragEnd()
            self.last_drag["result"] = ended
            self.drag_box = None
            self.Redraw()
        if result == c4d.MOUSEDRAGRESULT_ESCAPE or ended == c4d.MOUSEDRAGRESULT_ESCAPE:
            return True
        if shift or ctrl:
            self.owner._select_box(x, y, end_x, end_y, shift, ctrl)
        else:
            self.owner._select_box(x, y, end_x, end_y)
        return True


class _AtomSelectionContents:
    """A live structure editor with optional callbacks for scene updates."""

    def __init__(self, on_flatten, on_restore, on_selection=None,
                 on_apply_groups=None, on_local_appearance=None,
                 on_orientation=None, on_close=None):
        super().__init__()
        self.on_flatten = on_flatten
        self.on_restore = on_restore
        self.on_selection = on_selection
        self.on_apply_groups = on_apply_groups
        self.on_local_appearance = on_local_appearance
        self.on_orientation = on_orientation
        self.on_close = on_close
        self.selected_ids = set()
        self.selected_bonds = set()
        self._appearance = {"atom_radius": .30, "bond_radius": .08,
                            "atom_radius_overrides": {}, "bond_radius_overrides": {},
                            "element_radius_overrides": {}, "element_scales": {}}
        self.groups = {}
        self.groups_dirty = False
        self.orientation = "original"
        self.center_atom_ids = []
        self.ring_options = []
        self._center_menu_signature = None
        self.show_groups = True
        self.background_white = 0
        self.editing = True
        self._record = None
        self._graph = None
        self._image = _AtomImage(self)
        self._layout_ready = False
        self._status_text = "选择图片中的可见原子或键"

    def CreateLayout(self):
        fit = c4d.BFH_SCALEFIT
        self.GroupBegin(2100, fit | c4d.BFV_SCALEFIT, cols=1)
        self.GroupBorderSpace(8, 8, 8, 8)
        self.GroupSpace(6, 8)
        self.GroupBegin(2160, fit, cols=2)
        self.AddStaticText(2161, fit | getattr(c4d, "BFV_CENTER", 0), name="结构详情")
        add_brand_logo(
            self,
            2162,
            width=96,
            height=24,
            tooltip="出品：与可 | YUKE (DeepLeap) — 二维结构与局部外观编辑",
            align_right=True,
        )
        self.GroupEnd()
        self.AddUserArea(IMAGE, fit | c4d.BFV_SCALEFIT, initw=360, inith=280)
        self.AttachUserArea(self._image, IMAGE)
        self.GroupBegin(2118, fit, cols=4)
        self.AddStaticText(2119, c4d.BFH_LEFT, name="背景白度")
        self.AddEditNumberArrows(BACKGROUND_WHITE, c4d.BFH_LEFT, initw=58)
        self.AddSlider(BACKGROUND_SLIDER, fit, initw=120)
        add_icon(self, BACKGROUND_RESET, "reset.png", "恢复背景白度为 0", size=16)
        self.GroupEnd()
        self.ScrollGroupBegin(2133, fit | c4d.BFV_SCALEFIT,
                              c4d.SCROLLGROUP_VERT | c4d.SCROLLGROUP_AUTOVERT,
                              initw=240, inith=180)
        self.GroupBegin(EDIT_CONTROLS, fit | c4d.BFV_TOP, cols=1)
        self.AddStaticText(2114, fit, name="平面编辑")
        self.AddStaticText(COUNT, fit, name="已选 0 个原子、0 条键")
        self.GroupBegin(2110, fit, cols=4)
        add_action(self, SELECT_ALL, "全选", "选择所有二维可见原子及两端可见的键；隐式氢没有热点。")
        add_action(self, SELECT_RING, "选环", "一键选中环结构（先选中原子则补齐所在环；再次点击可循环切环）。")
        add_action(self, INVERT_SELECT, "反选", "反转当前二维可见重原子选区。")
        add_action(self, CLEAR, "清空", "清空二维原子和键的选择；保留平面分组。")
        self.GroupEnd()
        self.AddStaticText(2127, fit, name="局部外观")
        self.GroupBegin(2128, fit, cols=4)
        self.AddStaticText(2129, c4d.BFH_LEFT, name="原子大小")
        self.AddEditNumberArrows(LOCAL_ATOM_RADIUS, c4d.BFH_LEFT, initw=58)
        self.AddSlider(LOCAL_ATOM_SLIDER, fit, initw=100)
        add_icon(self, LOCAL_ATOM_RESET, "reset.png", "清除所选原子的局部大小覆盖", size=16)
        self.GroupEnd()
        self.AddStaticText(LOCAL_ATOM_NOTE, fit, name="先选择可见原子")
        self.GroupBegin(2130, fit, cols=4)
        self.AddStaticText(2131, c4d.BFH_LEFT, name="键粗细")
        self.AddEditNumberArrows(LOCAL_BOND_RADIUS, c4d.BFH_LEFT, initw=58)
        self.AddSlider(LOCAL_BOND_SLIDER, fit, initw=100)
        add_icon(self, LOCAL_BOND_RESET, "reset.png", "清除所选键的局部粗细覆盖", size=16)
        self.GroupEnd()
        self.AddStaticText(LOCAL_BOND_NOTE, fit, name="先选择可见化学键")
        add_action(self, LOCAL_RESET, "恢复所选", "清除所选原子和键的局部覆盖；原子恢复元素缩放或整体大小。")
        self.AddCheckbox(SHOW_GROUPS, c4d.BFH_LEFT, 0, 0, "显示平面关系")
        self.GroupBegin(2137, fit, cols=2)
        self.AddStaticText(2138, c4d.BFH_LEFT, name="整体方位")
        self.AddComboBox(PLANE, fit)
        self.GroupEnd()
        for index, label in enumerate(("原始方位", "自动对正", "XY", "XZ", "YZ")):
            self.AddChild(PLANE, index, label)
        self.GroupBegin(2139, fit, cols=2)
        self.AddStaticText(2140, c4d.BFH_LEFT, name="中心")
        self.AddComboBox(RING_CENTER, fit)
        self._center_menu_signature = None
        self.GroupEnd()
        self.GroupBegin(2141, c4d.BFH_LEFT, cols=2)
        add_action(self, SET_CENTER, "所选为中心", "以选中的可见原子为整体方位中心；多个原子取重心。")
        add_action(self, RESET_CENTER, "重置中心", "恢复自动中心：先选真正苯环，其次选六元环。")
        self.GroupEnd()
        self.GroupBegin(2111, fit, cols=3)
        add_action(self, FLATTEN, "拍平所选", "按二维图展开所选骨架，前后链段及分支从连接端点整体跟随；局部闭环会补齐。")
        add_action(self, ALL_FLATTEN, "全部拍平", "按二维图展开全部重原子骨架，支持非平面环；普通碳氢保留立体，羟基氢共面。")
        add_action(self, RESTORE, "还原", "恢复原始三维坐标，清除平面组；材质和球棍／填充显示保留。")
        self.GroupEnd()
        self.AddStaticText(STATUS, fit, name=self._status_text)
        self.GroupEnd()
        self.GroupEnd()
        self.GroupEnd()
        self._layout_ready = True
        self.set_editing(self.editing)
        return True

    def Message(self, msg, result):
        if hover_help(self, msg, result, {
                SHOW_GROUPS: "用半透明色块显示同一平面原子的关系。",
                BACKGROUND_WHITE: "白色叠加比例：0 为当前 C4D 界面背景，100 为纯白。",
                BACKGROUND_SLIDER: "拖动调节结构图背景白度；原子位置和分组不会改变。",
                LOCAL_ATOM_RADIUS: "所选原子的大小；滑杆 1–5，数字框允许超出范围。",
                LOCAL_ATOM_SLIDER: "统一所选原子大小；滑杆 1–5，数字框允许超出范围。",
                LOCAL_BOND_RADIUS: "所选键的粗细；滑杆 1–5，数字框允许超出范围。",
                LOCAL_BOND_SLIDER: "统一所选键粗细；滑杆 1–5，数字框允许超出范围。",
                PLANE: "整体旋转方位，不改变分子内部键长；拍平另用下方按钮。",
                RING_CENTER: "自动先选真正苯环，其次选六元环；也可选任一列出的环，以该环质心为中心。"}):
            return True
        return super().Message(msg, result)

    def InitValues(self):
        self.SetInt32(PLANE, ORIENTATIONS.index(self.orientation))
        self.SetBool(SHOW_GROUPS, self.show_groups)
        self.SetInt32(BACKGROUND_WHITE, self.background_white, min=0, max=100)
        self.SetInt32(BACKGROUND_SLIDER, self.background_white, min=0, max=100)
        self._refresh_centers()
        self._refresh_appearance()
        self._refresh_labels()
        return True

    def set_editing(self, editing):
        """Switch between large read-only preview and the plane editor."""
        self.editing = bool(editing)
        if self._layout_ready:
            self.HideElement(EDIT_CONTROLS, not self.editing)
            self.LayoutChanged(2100)
            self._image.Redraw()

    def _status(self, message):
        self._status_text = str(message)
        if self._layout_ready:
            self.SetString(STATUS, self._status_text)

    def _refresh_labels(self):
        if self._layout_ready:
            self.SetString(COUNT, "已选 %d 个原子、%d 条键" %
                           (len(self.selected_ids), len(self.selected_bonds)))
            self._image.Redraw()
            self._refresh_appearance()

    def set_appearance(self, style):
        """Sync global and local radii without changing the current selection."""
        for key in self._appearance:
            if key in style:
                self._appearance[key] = copy.deepcopy(style[key])
        self._refresh_appearance()

    def set_orientation(self, style):
        """Sync the whole-molecule display preset without issuing a new edit."""
        orientation = style.get("orientation", "original")
        self.orientation = orientation if orientation in ORIENTATIONS else "original"
        self.center_atom_ids = list(style.get("center_atom_ids") or [])
        if self._layout_ready:
            self.SetInt32(PLANE, ORIENTATIONS.index(self.orientation))
            self._refresh_centers()

    def _refresh_centers(self):
        if not self._layout_ready:
            return
        signature = (tuple((tuple(option["atom_ids"]), option["label"]) for option in self.ring_options),
                     tuple(sorted(self.center_atom_ids)))
        if signature == self._center_menu_signature:
            return
        self._center_menu_signature = signature
        self.FreeChildren(RING_CENTER)
        self.AddChild(RING_CENTER, 0, "自动（苯环→六元环）")
        selected = set(self.center_atom_ids)
        current = 0
        for index, option in enumerate(self.ring_options, 1):
            self.AddChild(RING_CENTER, index, option["label"])
            if set(option["atom_ids"]) == selected: current = index
        if selected and current == 0:
            current = len(self.ring_options) + 1
            self.AddChild(RING_CENTER, current, "所选原子（%d）" % len(selected))
        self.SetInt32(RING_CENTER, current)

    def _refresh_appearance(self):
        if not self._layout_ready:
            return
        elements = {atom["id"]: atom["element"] for atom in
                    (self._record or {}).get("atoms", [])}
        for keys, default_key, override_key, number, slider, note in (
                (self.selected_ids, "atom_radius", "atom_radius_overrides",
                 LOCAL_ATOM_RADIUS, LOCAL_ATOM_SLIDER, LOCAL_ATOM_NOTE),
                (self.selected_bonds, "bond_radius", "bond_radius_overrides",
                 LOCAL_BOND_RADIUS, LOCAL_BOND_SLIDER, LOCAL_BOND_NOTE)):
            if default_key == "atom_radius":
                values = [self._appearance[override_key].get(str(key),
                          self._appearance["element_radius_overrides"].get(
                              elements.get(key), self._appearance[default_key] *
                              self._appearance["element_scales"].get(elements.get(key), 1.)))
                          for key in sorted(keys)]
            else:
                values = [self._appearance[override_key].get(
                    str(key), self._appearance[default_key]) for key in sorted(keys)]
            mixed = len(set(values)) > 1
            value = values[0] if values else self._appearance[default_key]
            display = round(to_display(default_key, value), 1)
            low, high = display_limits(default_key)
            self.SetFloat(number, display, min=.1, max=1000000., step=.1)
            self.SetFloat(slider, min(high, max(low, display)),
                          min=low, max=high, step=.1)
            self.Enable(number, bool(keys))
            self.Enable(slider, bool(keys))
            self.Enable(LOCAL_ATOM_RESET if default_key == "atom_radius" else LOCAL_BOND_RESET,
                        bool(keys))
            self.SetString(note, "所选值不同；编辑后统一" if mixed else
                           ("已选 %d 项" % len(keys) if keys else "先选择可见原子" if
                            default_key == "atom_radius" else "先选择可见化学键"))
        self.Enable(LOCAL_RESET, bool(self.selected_ids or self.selected_bonds))

    def _describe_atom(self, atom_id):
        elements = {atom["id"]: atom.get("element", "?") for atom in (self._record or {}).get("atoms", [])}
        symbol = elements.get(atom_id, "?")
        return "原子 %s #%d · 左键点选 / Shift 加选 / Ctrl 增减 / 右键设平面组" % (symbol, atom_id)

    def _describe_bond(self, bond_key):
        endpoints = self._image.bonds.get(bond_key)
        if not endpoints:
            return "化学键 · 点击调局部粗细 / Shift 加选 / Ctrl 增减"
        a, b = endpoints
        elements = {atom["id"]: atom.get("element", "?") for atom in (self._record or {}).get("atoms", [])}
        order_label = "化学键"
        symbol = "—"
        for bond in (self._record or {}).get("bonds", []):
            if _bond_key(bond["a"], bond["b"]) == bond_key:
                if bond.get("aromatic"):
                    order_label, symbol = "芳香键", "~"
                elif float(bond.get("order", 1)) == 2.0:
                    order_label, symbol = "双键", "="
                elif float(bond.get("order", 1)) == 3.0:
                    order_label, symbol = "三键", "≡"
                else:
                    order_label, symbol = "单键", "—"
                break
        return "%s %s#%d%s%s#%d · 点击可调局部粗细 / Shift 加选" % (
            order_label, elements.get(a, "?"), a, symbol, elements.get(b, "?"), b
        )

    def _selection_changed(self):
        self._refresh_labels()
        self._status("右键分组" if self.selected_ids else
                     "已选键，可调整局部粗细" if self.selected_bonds else "点选／框选")
        if self.on_selection is not None:
            self.on_selection(sorted(self.selected_ids))

    def _select_box(self, x1, y1, x2, y2, shift=False, ctrl=False):
        """User-area local coordinates; supports Shift union and Ctrl toggle."""
        if abs(x2 - x1) < 4 and abs(y2 - y1) < 4:
            atom_id = self._image._hit(x2, y2)
            if atom_id is not None:
                if shift:
                    self.selected_ids.add(atom_id)
                    self.selected_bonds |= {
                        key for key, endpoints in self._image.bonds.items()
                        if set(endpoints) <= self.selected_ids
                    }
                elif ctrl:
                    self.selected_ids ^= {atom_id}
                else:
                    self.selected_ids = {atom_id}
                    self.selected_bonds.clear()
            else:
                bond_key = self._image._hit_bond(x2, y2)
                if bond_key:
                    if shift:
                        self.selected_bonds.add(bond_key)
                    elif ctrl:
                        self.selected_bonds ^= {bond_key}
                    else:
                        self.selected_ids.clear()
                        self.selected_bonds = {bond_key}
                elif not shift and not ctrl:
                    self.selected_ids.clear()
                    self.selected_bonds.clear()
            self._selection_changed()
            return
        left, top, width, height = self._image._image_box()
        source_w, source_h = self._image.source_size
        low_x, high_x = sorted((x1, x2))
        low_y, high_y = sorted((y1, y2))
        hits = {
            atom_id for atom_id, (px, py) in self._image.positions.items()
            if low_x <= left + px * width / source_w <= high_x and
               low_y <= top + py * height / source_h <= high_y}
        box_bonds = {key for key, endpoints in self._image.bonds.items()
                     if set(endpoints) <= hits}
        if shift:
            self.selected_ids |= hits
            self.selected_bonds |= {key for key, endpoints in self._image.bonds.items()
                                    if set(endpoints) <= self.selected_ids}
        elif ctrl:
            self.selected_ids ^= hits
            self.selected_bonds ^= box_bonds
        else:
            self.selected_ids = hits
            self.selected_bonds = box_bonds
        self._selection_changed()

    def _remove_from_groups(self):
        """Remove selected atoms from plane groups without renumbering."""
        if not self.selected_ids:
            self._status("请先选择至少一个重原子")
            return
        for group_id in list(self.groups):
            group = self.groups[group_id]
            group["atom_ids"] = [atom_id for atom_id in group["atom_ids"]
                                 if atom_id not in self.selected_ids]
            if not group["atom_ids"]:
                del self.groups[group_id]
        self.groups_dirty = True
        self._refresh_labels()
        self._commit_groups()

    def _assign_group(self, group_id=None):
        """Assign selected atoms to a group; new planes use the original graph."""
        if not self.selected_ids:
            self._status("请先选择至少一个重原子")
            return
        if group_id is None:
            if self._record is None:
                self._status("请先选择结构")
                return
            from .display_geometry import make_plane_group
            group_id = str(max((int(key) for key in self.groups), default=0) + 1)
            created = make_plane_group(self._record, sorted(self.selected_ids))
            group = {
                "atom_ids": list(created["atom_ids"]),
                "origin": list(created["origin"]),
                "normal": list(created["normal"]),
                "color": list(GROUP_COLORS[(int(group_id) - 1) % len(GROUP_COLORS)]),
            }
        else:
            group_id = str(group_id)
            if group_id not in self.groups:
                raise ValueError("平面组不存在")
            group = self.groups[group_id]
        for other_id in list(self.groups):
            if other_id == group_id:
                continue
            other = self.groups[other_id]
            other["atom_ids"] = [atom_id for atom_id in other["atom_ids"]
                                 if atom_id not in self.selected_ids]
            if not other["atom_ids"]:
                del self.groups[other_id]
        if group_id in self.groups:
            group["atom_ids"] = sorted(set(group["atom_ids"]) | self.selected_ids)
        self.groups[group_id] = group
        self.groups_dirty = True
        self._refresh_labels()
        self._commit_groups()

    def _commit_groups(self):
        if self.on_apply_groups is None:
            self._status("平面分组已记录")
            return
        success = self.on_apply_groups(copy.deepcopy(self.groups))
        if success is False:
            self._status("平面更新未完成，请查看主面板提示")
            return
        self.groups_dirty = False
        self._status("平面关系已更新")

    def _aromatic_ring_ids(self):
        """Compatibility helper: prefer benzene, or a ring touched by selection."""
        options = ring_center_options(self._record)
        selected = [option for option in options if set(option["atom_ids"]) & self.selected_ids]
        return list((selected or options)[0]["atom_ids"]) if options else []

    def _set_orientation(self, orientation=None, center_atom_ids=None):
        requested_orientation = orientation or self.orientation
        requested_center = (list(self.center_atom_ids) if center_atom_ids is None
                            else sorted(center_atom_ids))
        if self.on_orientation is not None:
            success = self.on_orientation(requested_orientation, requested_center)
            if success is False:
                self._status("方位未更新，请查看主面板提示")
                self.SetInt32(PLANE, ORIENTATIONS.index(self.orientation))
                self._center_menu_signature = None
                self._refresh_centers()
                return
        self.orientation = requested_orientation
        self.center_atom_ids = requested_center
        self._refresh_centers()
        self._status("方位与中心已更新")

    def _show_group_menu(self):
        """Called only from an actual native right mouse event."""
        if not self.selected_ids:
            self._status("请先选择至少一个重原子")
            return
        base = c4d.FIRST_POPUP_ID
        menu = c4d.BaseContainer()
        menu.InsData(base, "设为同一平面（新建）")
        mapping = {}
        for index, group_id in enumerate(sorted(self.groups, key=int), start=1):
            item_id = base + index
            menu.InsData(item_id, "移至平面 %s" % group_id)
            mapping[item_id] = group_id
        remove_id = base + len(mapping) + 1
        menu.InsData(0, "")
        menu.InsData(remove_id, "从平面组移除")
        choice = c4d.gui.ShowPopupDialog(self, menu, c4d.MOUSEPOS,
                                         c4d.MOUSEPOS)
        if choice == base:
            self._assign_group()
        elif choice in mapping:
            self._assign_group(mapping[choice])
        elif choice == remove_id:
            self._remove_from_groups()

    def set_groups(self, groups):
        """Replace pending groups with the model's committed configuration."""
        valid_ids = set(self._image.positions)
        incoming = {}
        occupied = set()
        for group_id, source in (groups or {}).items():
            key = str(group_id)
            if not key.isdecimal() or int(key) < 1 or not isinstance(source, dict):
                raise ValueError("平面组编号无效")
            atom_ids = [int(atom_id) for atom_id in source.get("atom_ids", [])]
            if (not atom_ids or len(set(atom_ids)) != len(atom_ids) or
                    not set(atom_ids) <= valid_ids or occupied.intersection(atom_ids)):
                raise ValueError("平面组原子编号无效或重复")
            occupied.update(atom_ids)
            color = source.get("color", GROUP_COLORS[(int(key) - 1) % len(GROUP_COLORS)])
            incoming[key] = {"atom_ids": sorted(atom_ids),
                             "origin": list(source["origin"]),
                             "normal": list(source["normal"]),
                             "color": list(color)}
        self.groups = copy.deepcopy(incoming)
        self.groups_dirty = False
        self._refresh_labels()

    def set_record(self, record):
        """Load a 360x280 PNG and bind its hotspots to original heavy-atom IDs."""
        if not isinstance(record, dict):
            raise ValueError("结构记录无效")
        graph = _graph_key(record)
        if graph != self._graph:
            self.selected_ids.clear()
            self.selected_bonds.clear()
            self.groups.clear()
            self.groups_dirty = False
        self._graph = graph
        self._record = record
        self.ring_options = ring_center_options(record)
        self._refresh_centers()

        size = record.get("thumbnail_size") or [360, 280]
        if (not isinstance(size, (list, tuple)) or len(size) != 2 or
                any(not isinstance(value, (int, float)) or
                    not math.isfinite(value) or value <= 0 for value in size)):
            raise ValueError("结构预览尺寸无效")
        self._image.source_size = (float(size[0]), float(size[1]))
        heavy_ids = {atom["id"] for atom in record.get("atoms", [])
                     if isinstance(atom, dict) and
                     isinstance(atom.get("id"), int) and
                     atom.get("element", "").upper() != "H"}
        positions = {}
        for key, value in (record.get("thumbnail_atom_positions") or {}).items():
            try:
                atom_id = int(key)
            except (TypeError, ValueError):
                continue
            if (atom_id not in heavy_ids or str(atom_id) != str(key) or
                    not isinstance(value, (list, tuple)) or len(value) != 2):
                continue
            px, py = value
            if (isinstance(px, (int, float)) and isinstance(py, (int, float))
                    and math.isfinite(px) and math.isfinite(py)):
                positions[atom_id] = (float(px), float(py))
        self._image.positions = positions
        self._image.bonds = {}
        for bond in record.get("bonds") or []:
            if not isinstance(bond, dict):
                continue
            a, b = bond.get("a"), bond.get("b")
            if isinstance(a, int) and isinstance(b, int) and a != b and a in positions and b in positions:
                self._image.bonds[_bond_key(a, b)] = (a, b)
        self.selected_ids.intersection_update(positions)
        self.selected_bonds.intersection_update(self._image.bonds)
        for group_id in list(self.groups):
            group = self.groups[group_id]
            group["atom_ids"] = [atom_id for atom_id in group["atom_ids"]
                                 if atom_id in positions]
            if not group["atom_ids"]:
                del self.groups[group_id]

        def load_bitmap(path):
            if not (isinstance(path, str) and os.path.isabs(path) and os.path.isfile(path)):
                return None
            bitmap = c4d.bitmaps.BaseBitmap()
            result, _is_movie = bitmap.InitWith(path)
            if result == c4d.IMAGERESULT_OK:
                return bitmap
            return None

        self._image.bitmap = load_bitmap(record.get("thumbnail"))
        self._image.light_bitmap = load_bitmap(record.get("transparent_dark_thumbnail"))
        self._image.dark_bitmap = load_bitmap(record.get("transparent_thumbnail"))
        self._image.hover_atom = None
        self._image.hover_bond = None
        self._refresh_labels()
        if self._image.bitmap is None and self._image.light_bitmap is None:
            self._status("二维结构图片不可用")
        elif not positions:
            self._status("二维图片中没有可选重原子")
        else:
            self._status("平面关系未同步" if self.groups_dirty else "点选／框选 · 右键分组")

    def _on_brand_click(self):
        msg_dialog = getattr(getattr(c4d, "gui", None), "MessageDialog", None)
        if not callable(msg_dialog):
            return
        lines = [
            "结构详情 · 二维平面编辑窗口",
            "出品：与可 | YUKE (DeepLeap)",
            "先理解研究，再呈现视觉",
            "GitHub: https://github.com/DeepLeap/scimol-c4d",
        ]
        if self._record:
            lines.append("")
            lines.append("当前结构：%s（%d 原子 / %d 键）" % (
                self._record.get("name", "当前分子"),
                len(self._record.get("atoms", [])),
                len(self._record.get("bonds", [])),
            ))
        msg_dialog("\n".join(lines))

    def Command(self, identifier, msg):
        if identifier == BACKGROUND_RESET:
            self.background_white = 0
            self.SetInt32(BACKGROUND_WHITE, 0, min=0, max=100)
            self.SetInt32(BACKGROUND_SLIDER, 0, min=0, max=100)
            self._image.Redraw()
            return True
        if identifier in (BACKGROUND_WHITE, BACKGROUND_SLIDER):
            white = self.GetInt32(identifier)
            self.background_white = max(0, min(100, white))
            self.SetInt32(BACKGROUND_WHITE, self.background_white, min=0, max=100)
            self.SetInt32(BACKGROUND_SLIDER, self.background_white, min=0, max=100)
            self._image.Redraw()
            return True
        if not self.editing and identifier != SHOW_GROUPS:
            return True
        if identifier == SELECT_ALL:
            self.selected_ids = set(self._image.positions)
            self.selected_bonds = set(self._image.bonds)
            self._selection_changed()
        elif identifier == SELECT_RING:
            visible = set(self._image.positions)
            rings = []
            for option in (self.ring_options or ring_center_options(self._record)):
                ring_ids = set(option["atom_ids"]) & visible
                if ring_ids:
                    rings.append((option["label"], ring_ids))
            if not rings:
                self._status("当前结构不含环")
                return True
            touched = [(label, ring_ids) for label, ring_ids in rings if ring_ids & self.selected_ids]
            if touched and any(not (ring_ids <= self.selected_ids) for _, ring_ids in touched):
                chosen_ids = set().union(*(ring_ids for _, ring_ids in touched))
                ring_label = "、".join(label for label, _ in touched)
            else:
                exact = next((i for i, (_, ring_ids) in enumerate(rings) if ring_ids == self.selected_ids), None)
                ring_label, chosen_ids = rings[(exact + 1) % len(rings)] if exact is not None else rings[0]
            self.selected_ids = set(chosen_ids)
            self.selected_bonds = {key for key, endpoints in self._image.bonds.items()
                                   if set(endpoints) <= self.selected_ids}
            self._selection_changed()
            self._status("已选中环：" + ring_label)
        elif identifier == INVERT_SELECT:
            self.selected_ids = set(self._image.positions) - self.selected_ids
            self.selected_bonds = {key for key, endpoints in self._image.bonds.items()
                                   if set(endpoints) <= self.selected_ids}
            self._selection_changed()
        elif identifier == CLEAR:
            self.selected_ids.clear()
            self.selected_bonds.clear()
            self._selection_changed()
        elif identifier in (LOCAL_ATOM_RADIUS, LOCAL_ATOM_SLIDER,
                            LOCAL_BOND_RADIUS, LOCAL_BOND_SLIDER):
            is_atom = identifier in (LOCAL_ATOM_RADIUS, LOCAL_ATOM_SLIDER)
            keys = sorted(self.selected_ids if is_atom else self.selected_bonds)
            if not keys:
                return True
            number = LOCAL_ATOM_RADIUS if is_atom else LOCAL_BOND_RADIUS
            slider = LOCAL_ATOM_SLIDER if is_atom else LOCAL_BOND_SLIDER
            radius_key = "atom_radius" if is_atom else "bond_radius"
            display = round(self.GetFloat(identifier), 1)
            if identifier == slider:
                low, high = display_limits(radius_key)
                display = min(high, max(low, display))
            if not isinstance(display, (int, float)) or not math.isfinite(display) or not 0 < display <= 1000000.:
                self._status("局部半径须为有限正数，最大 1000000")
                self._refresh_appearance()
                return True
            value = to_physical(radius_key, display)
            if not math.isfinite(value) or not 0 < value <= 1000000.:
                self._status("局部半径须为有限正数，最大 1000000")
                self._refresh_appearance()
                return True
            if self.on_local_appearance is not None:
                result = self.on_local_appearance("atoms" if is_atom else "bonds", keys, float(value))
                if isinstance(result, dict):
                    self.set_appearance(result)
                elif result is not False:
                    overrides = self._appearance["atom_radius_overrides" if is_atom else "bond_radius_overrides"]
                    for key in keys:
                        overrides[str(key)] = float(value)
            self._refresh_appearance()
        elif identifier in (LOCAL_RESET, LOCAL_ATOM_RESET, LOCAL_BOND_RESET):
            atoms = sorted(self.selected_ids) if identifier != LOCAL_BOND_RESET else []
            bonds = sorted(self.selected_bonds) if identifier != LOCAL_ATOM_RESET else []
            if not atoms and not bonds:
                return True
            if self.on_local_appearance is not None:
                result = self.on_local_appearance("reset", {"atoms": atoms, "bonds": bonds}, None)
                if isinstance(result, dict):
                    self.set_appearance(result)
                elif result is not False:
                    for atom_id in atoms:
                        self._appearance["atom_radius_overrides"].pop(str(atom_id), None)
                    for key in bonds:
                        self._appearance["bond_radius_overrides"].pop(key, None)
            self._refresh_appearance()
        elif identifier in (FLATTEN, ALL_FLATTEN):
            if identifier == FLATTEN and not self.selected_ids:
                self._status("请先选择至少一个重原子")
            else:
                success = self.on_flatten(None if identifier == ALL_FLATTEN else sorted(self.selected_ids), "auto")
                self._status("已拍平" if success is not False else
                             "拍平未完成，请查看主面板提示")
        elif identifier == RESTORE:
            success = self.on_restore()
            self._status("已还原" if success is not False else
                         "恢复未完成，请查看主面板提示")
        elif identifier == SHOW_GROUPS:
            self.show_groups = self.GetBool(SHOW_GROUPS)
            self._image.Redraw()
        elif identifier == PLANE:
            index = self.GetInt32(PLANE)
            if 0 <= index < len(ORIENTATIONS):
                self._set_orientation(ORIENTATIONS[index])
        elif identifier == SET_CENTER:
            if not self.selected_ids:
                self._status("先选择一个或多个可见原子")
            else:
                self._set_orientation(center_atom_ids=self.selected_ids)
        elif identifier == RING_CENTER:
            index = self.GetInt32(RING_CENTER)
            if index == 0:
                self._set_orientation(center_atom_ids=[])
            elif 1 <= index <= len(self.ring_options):
                self._set_orientation(center_atom_ids=self.ring_options[index-1]["atom_ids"])
        elif identifier == RESET_CENTER:
            self._set_orientation(center_atom_ids=[])
        return True


class AtomSelectionPanel(_AtomSelectionContents, c4d.gui.GeDialog):
    """Native asynchronous structure-details window."""

    def CreateLayout(self):
        self.SetTitle("结构详情")
        return super().CreateLayout()

    def AskClose(self):
        if self.on_close is not None:
            self.on_close()
        return False


AtomSelectionDialog = AtomSelectionPanel
