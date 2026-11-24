"""Native folder tree and thumbnail grid for the molecule resource browser.

Folder nodes are dictionaries with id, name, parent, and child-id list keys.
The owner supplies folder_nodes, folder_current, records, selected,
selected_cards, and the
_browse_folder, _select, _resource_menu, and _drag_asset callbacks.
"""

import math
import os

import c4d


class FolderFunctions(c4d.gui.TreeViewFunctions):
    """Single-selection hierarchy backed by the owner's folder nodes."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self._opened = {}

    def _nodes(self):
        return {node["id"]: node for node in self.owner.folder_nodes}

    def _siblings(self, obj):
        parent = obj.get("parent")
        if parent is None:
            return [node for node in self.owner.folder_nodes if node.get("parent") is None]
        node = self._nodes().get(parent)
        if node is None:
            return []
        by_id = self._nodes()
        return [by_id[child] for child in node.get("children", ()) if child in by_id]

    def GetFirst(self, root, userdata):
        return next((node for node in self.owner.folder_nodes
                     if node.get("parent") is None), None)

    def GetDown(self, root, userdata, obj):
        by_id = self._nodes()
        return next((by_id[child] for child in obj.get("children", ())
                     if child in by_id), None)

    def GetNext(self, root, userdata, obj):
        siblings = self._siblings(obj)
        for index, node in enumerate(siblings):
            if node["id"] == obj["id"]:
                return siblings[index + 1] if index + 1 < len(siblings) else None
        return None

    def GetPred(self, root, userdata, obj):
        siblings = self._siblings(obj)
        for index, node in enumerate(siblings):
            if node["id"] == obj["id"]:
                return siblings[index - 1] if index else None
        return None

    def GetId(self, root, userdata, obj):
        for index, node in enumerate(self.owner.folder_nodes, 1):
            if node["id"] == obj["id"]:
                return index
        return 0

    def GetName(self, root, userdata, obj):
        return obj["name"]

    def GetNameForEdit(self, root, userdata, obj):
        return self.GetName(root, userdata, obj)

    def GetLineHeight(self, root, userdata, obj, col, area):
        return 25

    def GetColumnWidth(self, root, userdata, obj, col, area):
        return area.DrawGetTextWidth(self.GetName(root, userdata, obj)) + 30

    def DrawCell(self, root, userdata, obj, col, drawinfo, bgcolor):
        area = drawinfo["frame"]
        x, y = drawinfo["xpos"], drawinfo["ypos"]
        height = drawinfo["height"]
        selected = self.IsSelected(root, userdata, obj)
        color = (getattr(c4d, "COLOR_TEXT_SELECTED", c4d.COLOR_TEXT)
                 if selected else c4d.COLOR_TEXT)
        area.DrawSetPen(color)
        icon_y = y + max(1, (height - 13)//2)
        area.DrawLine(x+3, icon_y+4, x+6, icon_y+4)
        area.DrawLine(x+6, icon_y+4, x+8, icon_y+2)
        area.DrawLine(x+8, icon_y+2, x+14, icon_y+2)
        area.DrawLine(x+3, icon_y+4, x+3, icon_y+12)
        area.DrawLine(x+3, icon_y+12, x+18, icon_y+12)
        area.DrawLine(x+18, icon_y+12, x+18, icon_y+4)
        area.DrawLine(x+18, icon_y+4, x+3, icon_y+4)
        area.DrawSetTextCol(color, bgcolor)
        area.DrawText(self.GetName(root, userdata, obj), x+24,
                      y + max(0, (height-area.DrawGetFontHeight())//2))
        return bgcolor

    def IsOpened(self, root, userdata, obj):
        return self._opened.get(obj["id"], obj.get("parent") is None)

    def Open(self, root, userdata, obj, onoff):
        self._opened[obj["id"]] = bool(onoff)

    def IsSelectable(self, root, userdata, obj):
        return True

    def IsSelected(self, root, userdata, obj):
        return obj["id"] == self.owner.folder_current

    def Select(self, root, userdata, obj, mode):
        if mode != c4d.SELECTION_SUB:
            self.owner._browse_folder(obj["id"])


class ThumbnailArea(c4d.gui.GeUserArea):
    """Responsive fixed-card grid with contained molecular thumbnails."""

    CARD_WIDTH = 100
    CARD_HEIGHT = 106
    GAP = 8
    MARGIN = 8
    EMPTY_HEIGHT = 360
    DRAG_THRESHOLD = 5.0

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self._bitmap_cache = {}
        self._anchor = None
        self._marquee = None

    def _selection(self):
        cards = getattr(self.owner, "selected_cards", None)
        if cards is None:
            cards = {self.owner.selected} if self.owner.selected >= 0 else set()
        return {index for index in cards if 0 <= index < len(self.owner.records)}

    def _redraw(self):
        if hasattr(self, "Redraw"):
            self.Redraw()

    def _set_selection(self, cards, active=None, force_focus=False):
        cards = {index for index in cards if 0 <= index < len(self.owner.records)}
        has_focus = (getattr(self.owner, "current_record", None) is not None or
                     0 <= self.owner.selected < len(self.owner.records))
        if active is not None and active in cards and (force_focus or not has_focus):
            if self.owner._select(active) is False:
                self._redraw()
                return False
        # Multi-selection manages resources; a plain click changes the preview.
        self.owner.selected_cards = cards
        self._redraw()
        return True

    def _qualifiers(self, msg):
        key = getattr(c4d, "BFM_INPUT_QUALIFIER", None)
        try:
            mask = msg.GetInt32(key) if key is not None else 0
        except (KeyError, TypeError, AttributeError):
            mask = 0
        return bool(mask & getattr(c4d, "QUALIFIER_SHIFT", 0)), bool(mask & getattr(c4d, "QUALIFIER_CTRL", 0))

    def _click_card(self, index, shift=False, ctrl=False):
        previous_anchor = self._anchor
        previous = self._selection()
        if shift:
            anchor = self._anchor
            if anchor is None or not 0 <= anchor < len(self.owner.records):
                anchor = self.owner.selected if self.owner.selected in previous else index
            picked = set(range(min(anchor, index), max(anchor, index)+1))
            cards = previous | picked if ctrl else picked
            active = index
        elif ctrl:
            cards = previous ^ {index}
            active = index if index in cards else (min(cards) if cards else None)
            self._anchor = index
        else:
            cards = {index}
            active = index
            self._anchor = index
        if self._set_selection(cards, active, force_focus=not shift and not ctrl) is False:
            self._anchor = previous_anchor

    def _cards_in_box(self, x1, y1, x2, y2):
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        hits = set()
        for index in range(len(self.owner.records)):
            card_x, card_y = self._card_box(index)
            if (left <= card_x+self.CARD_WIDTH-1 and right >= card_x and
                    top <= card_y+self.CARD_HEIGHT-1 and bottom >= card_y):
                hits.add(index)
        return hits

    def _frame_selection(self, hits, previous, shift=False, ctrl=False):
        if shift:
            cards = previous | hits
        elif ctrl:
            cards = previous ^ hits
        else:
            cards = hits
        active = min(hits & cards) if hits & cards else (min(cards) if cards else None)
        self._set_selection(cards, active)
        if active is not None:
            self._anchor = active

    def _columns(self):
        width = max(self.CARD_WIDTH + 2*self.MARGIN, self.GetWidth())
        return max(1, (width - 2*self.MARGIN + self.GAP)//
                   (self.CARD_WIDTH + self.GAP))

    def GetMinSize(self):
        rows = math.ceil(len(self.owner.records)/self._columns())
        height = 2*self.MARGIN + rows*(self.CARD_HEIGHT+self.GAP)
        return (self.CARD_WIDTH + 2*self.MARGIN,
                max(self.EMPTY_HEIGHT, height))

    def _card_box(self, index):
        columns = self._columns()
        return (self.MARGIN + (index % columns)*(self.CARD_WIDTH+self.GAP),
                self.MARGIN + (index // columns)*(self.CARD_HEIGHT+self.GAP))

    def _hit(self, x, y):
        if x < self.MARGIN or y < self.MARGIN:
            return None
        col = (x-self.MARGIN)//(self.CARD_WIDTH+self.GAP)
        row = (y-self.MARGIN)//(self.CARD_HEIGHT+self.GAP)
        if col >= self._columns():
            return None
        index = row*self._columns()+col
        left, top = self._card_box(index)
        if (index >= len(self.owner.records) or x >= left+self.CARD_WIDTH or
                y >= top+self.CARD_HEIGHT):
            return None
        return index

    def _bitmap(self, path):
        if not path or not isinstance(path, str) or not os.path.isfile(path):
            return None
        stamp = os.path.getmtime(path)
        cached = self._bitmap_cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        bitmap = c4d.bitmaps.BaseBitmap()
        initialized = bitmap.InitWith(path)
        if not initialized or initialized[0] != c4d.IMAGERESULT_OK:
            return None
        self._bitmap_cache[path] = (stamp, bitmap)
        return bitmap

    def DrawMsg(self, x1, y1, x2, y2, msg):
        self.OffScreenOn()
        background = c4d.COLOR_BG
        native = self.GetColorRGB(background)
        luma = (native["r"] + native["g"] + native["b"]) / 765.0
        border = getattr(c4d, "COLOR_BORDER_ACTIVE_1", c4d.COLOR_TEXT)
        accent = getattr(c4d, "COLOR_BGSELECTEDTEXT", border)
        selected_bg = getattr(c4d, "COLOR_ICONS_BG_ACTIVE", background)
        self.DrawSetPen(background)
        self.DrawRectangle(0, 0, self.GetWidth(), self.GetHeight())
        if not self.owner.records:
            self.DrawSetTextCol(c4d.COLOR_TEXT, background)
            text = (getattr(self.owner, "search_message", "") or "正在搜索…"
                    if getattr(self.owner, "search_pending", False) else
                    getattr(self.owner, "search_message", "") or "未找到匹配结构"
                    if getattr(self.owner, "folder_current", "") == "search" else
                    "此文件夹暂无结构")
            self.DrawText(text, self.MARGIN + 4, self.MARGIN + 10)
            return True
        for index, record in enumerate(self.owner.records):
            left, top = self._card_box(index)
            selected = index in self._selection()
            is_live = False
            if (getattr(self.owner, "session_active", False) and
                    getattr(self.owner, "current_record", None) is not None and
                    hasattr(self.owner, "_resource_key")):
                is_live = (self.owner._resource_key(record) ==
                           self.owner._resource_key(self.owner.current_record))
            self.DrawSetPen(accent if selected else border)
            self.DrawRectangle(left, top, left+self.CARD_WIDTH-1,
                               top+self.CARD_HEIGHT-1)
            card_bg = selected_bg if selected else background
            self.DrawSetPen(card_bg)
            self.DrawRectangle(left+1, top+1, left+self.CARD_WIDTH-2,
                               top+self.CARD_HEIGHT-2)
            if is_live:
                self.DrawSetPen(accent)
                self.DrawRectangle(left+1, top+1, left+self.CARD_WIDTH-2, top+3)
            if record.get("configuration_id"):
                self.DrawSetPen(accent)
                self.DrawRectangle(left+self.CARD_WIDTH-9, top+5,
                                   left+self.CARD_WIDTH-5, top+9)
            ink_path = (record.get("transparent_thumbnail") if luma >= 0.5
                        else record.get("transparent_dark_thumbnail"))
            bitmap = self._bitmap(ink_path)
            if bitmap is not None:
                source_w, source_h = bitmap.GetBw(), bitmap.GetBh()
                if source_w > 0 and source_h > 0:
                    scale = min(88/source_w, 76/source_h)
                    draw_w = max(1, int(round(source_w*scale)))
                    draw_h = max(1, int(round(source_h*scale)))
                    image_x = left+(self.CARD_WIDTH-draw_w)//2
                    image_y = top+4+(76-draw_h)//2
                    self.DrawBitmap(bitmap, image_x, image_y, draw_w, draw_h,
                                    0, 0, source_w, source_h,
                                    c4d.BMP_NORMALSCALED | c4d.BMP_ALLOWALPHA)
            name = str(record.get("name") or "未命名")
            if len(name) > 10:
                name = name[:9] + "…"
            text_color = (getattr(c4d, "COLOR_TEXT_SELECTED", c4d.COLOR_TEXT)
                          if selected and card_bg != background else c4d.COLOR_TEXT)
            self.DrawSetTextCol(text_color, card_bg)
            label_width = self.DrawGetTextWidth(name)
            self.DrawText(name, left + max(5, (self.CARD_WIDTH-label_width)//2),
                          top+83)
        if self._marquee is not None:
            x1, y1, x2, y2 = self._marquee
            left, right = sorted((int(x1), int(x2)))
            top, bottom = sorted((int(y1), int(y2)))
            self.DrawSetPen(accent)
            self.DrawLine(left, top, right, top)
            self.DrawLine(right, top, right, bottom)
            self.DrawLine(right, bottom, left, bottom)
            self.DrawLine(left, bottom, left, top)
        return True

    def Message(self, msg, result):
        if msg.GetId() == c4d.BFM_GETCURSORINFO:
            offset = self.Global2Local()
            if offset is not None:
                x = msg.GetInt32(c4d.BFM_INPUT_X) + offset["x"]
                y = msg.GetInt32(c4d.BFM_INPUT_Y) + offset["y"]
                index = self._hit(x, y)
                if index is not None:
                    record = self.owner.records[index]
                    tip = str(record.get("name") or "未命名")
                    details = []
                    if record.get("formula"):
                        details.append(str(record["formula"]))
                    atoms = record.get("atoms")
                    if isinstance(atoms, list) and atoms:
                        details.append("%d 原子" % len(atoms))
                    if record.get("configuration_id"):
                        details.append("配置预设")
                    elif record.get("list_source"):
                        details.append(str(record["list_source"]))
                    if record.get("usage_count"):
                        details.append("使用 %d 次" % record["usage_count"])
                    if details:
                        tip += " · " + " · ".join(details)
                    result.SetId(c4d.BFM_GETCURSORINFO)
                    result.SetString(c4d.RESULT_BUBBLEHELP, tip)
                    return True
        return super().Message(msg, result)

    def InputEvent(self, msg):
        if (msg.GetInt32(c4d.BFM_INPUT_DEVICE) != c4d.BFM_INPUT_MOUSE or
                not msg.GetInt32(c4d.BFM_INPUT_VALUE)):
            return False
        channel = msg.GetInt32(c4d.BFM_INPUT_CHANNEL)
        if channel not in (c4d.BFM_INPUT_MOUSELEFT, c4d.BFM_INPUT_MOUSERIGHT):
            return False
        offset = self.Global2Local()
        if offset is None:
            return False
        x = msg.GetInt32(c4d.BFM_INPUT_X)+offset["x"]
        y = msg.GetInt32(c4d.BFM_INPUT_Y)+offset["y"]
        index = self._hit(x, y)
        if channel == c4d.BFM_INPUT_MOUSERIGHT:
            if index is not None:
                self.owner._resource_menu(index)
                return True
            return False
        shift, ctrl = self._qualifiers(msg)
        dbl_key = getattr(c4d, "BFM_INPUT_DOUBLECLICK", None)
        try:
            is_double = bool(msg.GetInt32(dbl_key)) if dbl_key is not None else False
        except (KeyError, TypeError, AttributeError):
            is_double = False
        if is_double and index is not None and not shift and not ctrl:
            self._click_card(index, False, False)
            return True
        previous = self._selection()
        self.MouseDragStart(c4d.BFM_INPUT_MOUSELEFT, float(x), float(y),
                            c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE)
        end_x, end_y = float(x), float(y)
        dragging = False
        outcome = None
        try:
            while True:
                outcome, dx, dy, _channels = self.MouseDrag()
                if outcome != c4d.MOUSEDRAGRESULT_CONTINUE:
                    break
                # C4D reports previous minus current; convert to local endpoint.
                end_x -= dx
                end_y -= dy
                if ((end_x-x)**2 + (end_y-y)**2 >= self.DRAG_THRESHOLD**2):
                    dragging = True
                    self._marquee = (x, y, end_x, end_y)
                    self._redraw()
        finally:
            ended = self.MouseDragEnd()
            self._marquee = None
            self._redraw()
        if outcome == c4d.MOUSEDRAGRESULT_ESCAPE or ended == c4d.MOUSEDRAGRESULT_ESCAPE:
            return True
        if index is None:
            if dragging:
                self._frame_selection(self._cards_in_box(x, y, end_x, end_y),
                                      previous, shift, ctrl)
            else:
                self._anchor = None
                self._set_selection(set())
        elif dragging:
            self._frame_selection(self._cards_in_box(x, y, end_x, end_y),
                                  previous, shift, ctrl)
        else:
            self._click_card(index, shift, ctrl)
        return True
