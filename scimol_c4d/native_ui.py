"""Small native Cinema 4D controls shared by the molecule editor."""

import c4d
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
_GeUserArea = getattr(getattr(c4d, "gui", None), "GeUserArea", object)
_DEFAULT_BRAND_DIALOG = (
    "分子球棍生成器 · SciMol C4D\n"
    "出品：与可 | YUKE (DeepLeap)\n"
    "先理解研究，再呈现视觉\n"
    "GitHub: https://github.com/DeepLeap/scimol-c4d"
)


class BrandLogoArea(_GeUserArea):
    """Frameless native header logo displaying the official YUKE lockup."""

    def __init__(self, owner, width=104, height=26, tooltip=None, align_right=True):
        if _GeUserArea is not object:
            super().__init__()
        self._owner = owner
        self._width = max(48, int(width))
        self._height = max(18, int(height))
        self._tooltip = tooltip or "出品：与可 | YUKE (DeepLeap)"
        self._align_right = bool(align_right)
        self._bitmaps = {}

    def GetMinSize(self):
        return (self._width, self._height)

    def _logo_bitmap(self, light_theme):
        filename = "yuke_lockup_light.png" if light_theme else "yuke_lockup_dark.png"
        path = ASSETS / filename
        if not path.is_file():
            path = ASSETS / "yuke_lockup_dark.png"
        key = str(path)
        if key in self._bitmaps:
            return self._bitmaps[key]
        base_bitmap_cls = getattr(getattr(c4d, "bitmaps", None), "BaseBitmap", None)
        if base_bitmap_cls is None or not path.is_file():
            return None
        bitmap = base_bitmap_cls()
        result = bitmap.InitWith(key)
        if result[0] == getattr(c4d, "IMAGERESULT_OK", 1):
            self._bitmaps[key] = bitmap
            return bitmap
        return None

    def DrawMsg(self, x1, y1, x2, y2, msg):
        if hasattr(self, "OffScreenOn"):
            self.OffScreenOn()
        width = max(1, int(self.GetWidth()))
        height = max(1, int(self.GetHeight()))
        bg_pen = getattr(c4d, "COLOR_BG", 0)
        self.DrawSetPen(bg_pen)
        self.DrawRectangle(0, 0, width, height)
        light_theme = False
        if hasattr(self, "GetColorRGB"):
            try:
                rgb = self.GetColorRGB(bg_pen)
                if rgb:
                    luma = (rgb["r"] + rgb["g"] + rgb["b"]) / 3.0
                    light_theme = luma >= 145.0
            except Exception:
                light_theme = False
        bitmap = self._logo_bitmap(light_theme)
        if bitmap is None:
            return True
        bw, bh = max(1, bitmap.GetBw()), max(1, bitmap.GetBh())
        avail_w = max(1, width - 4)
        avail_h = max(1, height - 4)
        scale = min(avail_w / float(bw), avail_h / float(bh))
        dw = max(1, int(round(bw * scale)))
        dh = max(1, int(round(bh * scale)))
        dx = max(0, width - dw - 2) if self._align_right else max(0, (width - dw) // 2)
        dy = max(0, (height - dh) // 2)
        flags = getattr(c4d, "BMP_NORMALSCALED", 0) | getattr(c4d, "BMP_ALLOWALPHA", 0)
        self.DrawBitmap(bitmap, dx, dy, dw, dh, 0, 0, bw, bh, flags)
        return True

    def Message(self, msg, result):
        if msg is not None and msg.GetId() == getattr(c4d, "BFM_GETCURSORINFO", -1):
            result.SetId(getattr(c4d, "BFM_GETCURSORINFO", 0))
            result.SetString(getattr(c4d, "RESULT_BUBBLEHELP", 0), self._tooltip)
            cursor_key = getattr(c4d, "RESULT_CURSOR", None)
            hand_cursor = getattr(c4d, "MOUSE_POINT_HAND", None)
            if cursor_key is not None and hand_cursor is not None:
                result.SetInt32(cursor_key, hand_cursor)
            return True
        parent_msg = getattr(_GeUserArea, "Message", None)
        if callable(parent_msg):
            return parent_msg(self, msg, result)
        return False

    def InputEvent(self, msg):
        if msg is None:
            return False
        if (
            msg.GetInt32(getattr(c4d, "BFM_INPUT_DEVICE", 0))
            == getattr(c4d, "BFM_INPUT_MOUSE", -1)
            and msg.GetInt32(getattr(c4d, "BFM_INPUT_CHANNEL", 0))
            == getattr(c4d, "BFM_INPUT_MOUSELEFT", -1)
        ):
            handler = getattr(self._owner, "_on_brand_click", None)
            if callable(handler):
                handler()
            else:
                msg_dialog = getattr(getattr(c4d, "gui", None), "MessageDialog", None)
                if callable(msg_dialog):
                    msg_dialog(_DEFAULT_BRAND_DIALOG)
            return True
        return False


def add_brand_logo(dialog, identifier, width=104, height=26, tooltip=None, align_right=True):
    """Attach a crisp theme-aware YUKE brand lockup inside a dialog header."""
    area = BrandLogoArea(
        dialog, width=width, height=height, tooltip=tooltip, align_right=align_right
    )
    if not hasattr(dialog, "_brand_logos"):
        dialog._brand_logos = {}
    dialog._brand_logos[identifier] = area
    if hasattr(dialog, "AddUserArea") and hasattr(dialog, "AttachUserArea"):
        h_flag = (
            getattr(c4d, "BFH_RIGHT", 0)
            if align_right
            else getattr(c4d, "BFH_LEFT", 0)
        )
        v_flag = getattr(c4d, "BFV_CENTER", 0)
        dialog.AddUserArea(identifier, h_flag | v_flag, initw=width, inith=height)
        dialog.AttachUserArea(area, identifier)
    return area


def add_action(dialog, identifier, label, help_text, toggle=False):
    """Add a compact native button with theme-provided interaction feedback."""
    if not hasattr(dialog, "action_help"):
        dialog.action_help = {}
    dialog.action_help[identifier] = help_text
    # Default native height follows the host's UI scaling. Left alignment keeps
    # buttons compact when a pane grows; labels determine their minimum width.
    return dialog.AddButton(identifier, c4d.BFH_LEFT, initw=0, inith=0,
                            name=label, buttonStyle=c4d.DR_BUTTON_STYLE_NORMAL)


def set_action_active(dialog, identifier, active):
    """Give a native button the same blue active colors as C4D's native tabs."""
    sources = ((c4d.COLOR_BG_BUTTON, c4d.COLOR_ICONS_BG_ACTIVE if active else c4d.COLOR_BG_BUTTON),
               (c4d.COLOR_BG_BUTTON_HIGHLIGHTED, c4d.COLOR_ICONS_BG_ACTIVE_HIGHLIGHT
                if active else c4d.COLOR_BG_BUTTON_HIGHLIGHTED),
               (c4d.COLOR_TEXT_BUTTON, c4d.COLOR_QUICKTAB_TEXT_ACTIVE
                if active else c4d.COLOR_TEXT_BUTTON))
    for target, source in sources:
        dialog.SetDefaultColor(identifier, target, c4d.gui.GetGuiWorldColor(source))


def add_icon(dialog, identifier, filename, help_text, toggle=False, size=24):
    settings = c4d.BaseContainer()
    settings.SetBool(c4d.BITMAPBUTTON_BUTTON, True)
    settings.SetInt32(c4d.BITMAPBUTTON_OUTBORDER, c4d.BORDER_ROUND)
    settings.SetInt32(c4d.BITMAPBUTTON_BORDER, c4d.BORDER_IN)
    settings.SetInt32(c4d.BITMAPBUTTON_BACKCOLOR, c4d.COLOR_BG_BUTTON)
    settings.SetBool(c4d.BITMAPBUTTON_DISABLE_FADING, False)
    settings.SetBool(c4d.BITMAPBUTTON_TOGGLE, toggle)
    settings.SetInt32(c4d.BITMAPBUTTON_FORCE_SIZE, size)
    settings.SetInt32(c4d.BITMAPBUTTON_FORCE_SIZE_Y, size)
    settings.SetString(c4d.BITMAPBUTTON_TOOLTIP, help_text)
    control = dialog.AddCustomGui(identifier, c4d.CUSTOMGUI_BITMAPBUTTON, "",
                                  c4d.BFH_LEFT | c4d.BFV_TOP, 0, 0, settings)
    if control:
        control.SetImage(str(ASSETS / filename))
    if not hasattr(dialog, "icon_controls"):
        dialog.icon_controls = {}
    dialog.icon_controls[identifier] = control
    return control


def hover_help(dialog, msg, result, help_map):
    """Provide native bubble help for ordinary checkboxes and input fields."""
    if msg.GetId() != c4d.BFM_GETCURSORINFO:
        return False
    offset = dialog.Screen2Local()
    if offset is None:
        return False
    x = msg.GetInt32(c4d.BFM_DRAG_SCREENX) + offset['x']
    y = msg.GetInt32(c4d.BFM_DRAG_SCREENY) + offset['y']
    descriptions = dict(getattr(dialog, "action_help", {}))
    descriptions.update(help_map)
    for identifier, description in descriptions.items():
        bounds = dialog.GetItemDim(identifier)
        if bounds and bounds['w'] > 0 and bounds['h'] > 0 and (
                bounds['x'] <= x < bounds['x'] + bounds['w'] and
                bounds['y'] <= y < bounds['y'] + bounds['h']):
            result.SetId(c4d.BFM_GETCURSORINFO)
            result.SetString(c4d.RESULT_BUBBLEHELP, description)
            return True
    return False
