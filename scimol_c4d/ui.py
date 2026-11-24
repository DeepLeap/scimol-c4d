"""Compact native C4D panel. Worker threads never call C4D APIs."""

import builtins
import copy
import queue
import re
import traceback
import os

import c4d

from . import c4d_builder
from .backend import Backend, DATA
from .library import Library
from .usage import UsageStore
from .records import DEFAULT_STYLE, DEPICTION_VERSION, normalized_style, validate_record, normalized_plane_groups, record_integrity
from .display_geometry import flatten_overrides, apply_plane_groups
from .search_index import is_valid_formula, normalize_query_text

INPUT, INPUT_KIND, RESOLVE, PASTE, IMPORT = 1001, 1002, 1003, 1004, 1005
COMMON, FAVORITES, READ_MODEL = 1010, 1011, 1012
CARDS, PREVIOUS, NEXT, PAGE, SELECTED, WARNING = 1100, 1101, 1102, 1103, 1104, 1105
SCALE, ATOM_RADIUS, BOND_RADIUS, SPACING = 1201, 1202, 1203, 1204
BOND_MODE, BOND_MATERIAL, HYDROGENS, QUALITY = 1210, 1211, 1212, 1213
BOND_COLOR, ELEMENT, ELEMENT_COLOR, APPLY_COLOR = 1220, 1221, 1222, 1223
GENERATE, UPDATE, CANCEL, SAVE = 1301, 1302, 1303, 1304
LABEL, CATEGORY, REMOVE, EXPORT, IMPORT_LIBRARY = 1310, 1311, 1312, 1313, 1314
STATUS, DETAILS = 1400, 1401
CARD_BASE = 5000
FLATTEN_ALL, ATOM_SELECT, RESTORE_3D, FLATTEN_PLANE = 1250, 1251, 1252, 1253
SPACE_FILL, BALL_STICK, ATOM_LABEL = 1260, 1261, 1262
ROOT_LAYOUT, EDIT_MODE, EDITOR_GROUP, EDITOR_SUB = 1, 1420, 1421, 1422
PAGE_SIZE = 6
ELEMENTS = ("C", "H", "O", "N", "S", "P", "F", "Cl", "Br", "I")
ELEMENT_COLORS = {"C": [0.18, 0.18, 0.18], "H": [0.93, 0.93, 0.93],
                  "O": [0.85, 0.12, 0.10], "N": [0.12, 0.30, 0.85],
                  "S": [0.95, 0.75, 0.08], "P": [0.95, 0.45, 0.10],
                  "F": [0.30, 0.78, 0.25], "Cl": [0.20, 0.70, 0.20],
                  "Br": [0.58, 0.18, 0.12], "I": [0.45, 0.22, 0.62]}
_STYLE_CONTROLS = (ATOM_RADIUS, BOND_RADIUS, SPACING, BOND_MODE,
                   BOND_MATERIAL, HYDROGENS, QUALITY, BOND_COLOR, ELEMENT,
                   ELEMENT_COLOR, APPLY_COLOR)


class MoleculeDialog(c4d.gui.GeDialog):
    def __init__(self):
        super().__init__()
        self.backend = Backend()
        self.library = Library(DATA)
        self.usage = UsageStore(DATA)
        self.records = []
        self.builtins = []
        self.favorite_items = {}
        self.view = "common"
        self.page = 0
        self.selected = -1
        self.current_record = None
        self.style = copy.deepcopy(DEFAULT_STYLE)
        self.busy = False
        self.alive = True
        self.card_controls = []
        self.atom_selector = None
        self.selector_pending = False
        self.selector_root = None
        self.selector_drafts = []
        self.editor = None
        self.show_common = True
        self.show_favorites = False
        self.action_controls = []
        self.status_text = ""
        self.selected_text = ""
        self.warning_text = ""

    def CreateLayout(self):
        from .panel_layout import build
        return build(self, __import__(__name__, fromlist=["*"]))

    def InitValues(self):
        self.SetInt32(INPUT_KIND, 0)
        self.SetBool(COMMON, self.show_common)
        self.SetBool(FAVORITES, self.show_favorites)
        self.SetBool(EDIT_MODE, False)
        self.SetString(CATEGORY, "未分类")
        self._set_style(self.style)
        self.SetTimer(200)
        self._start({"action": "builtin"}, "common")
        return True

    def _status(self, value):
        self.status_text = str(value)
        self.SetString(STATUS, self.status_text if len(self.status_text) <= 22 else self.status_text[:21] + "…")

    def Message(self, msg, result):
        from .native_ui import hover_help
        help_map = {
            COMMON: "按成功生成次数自动排序。可与收藏同时显示，也可以关闭。",
            FAVORITES: "显示本地收藏；与常用列表互不影响。",
            EDIT_MODE: "展开同一窗口中的二维平面编辑；点选或框选后右键分组，点击更新三维提交。",
            ATOM_RADIUS: "调整球的大小；填充模式下为元素半径的倍率。允许球体交叠。",
            BOND_RADIUS: "调整棍的粗细；材质与球保持独立。",
            SPACING: "双键和三键的平行棍间距。",
            BOND_MODE: "多键按原始键级显示；单棍仅改变显示，不改变结构。",
            BOND_MATERIAL: "统一键色或按两端元素分色；均为独立的键材质。",
            HYDROGENS: "显示或隐藏氢；拍平时普通碳氢保留立体，羟基氢共面。",
            QUALITY: "球体细分精度；中精度为默认值。",
            BOND_COLOR: "只控制键材质，不改变原子球。",
            ELEMENT_COLOR: "所选元素的球色；点击应用球色后更新模型。",
            INPUT: "输入常用中文名称、英文名称、分子式或 SMILES。",
            STATUS: self.status_text,
            SELECTED: self.selected_text,
            WARNING: self.warning_text,
        }
        if hover_help(self, msg, result, help_map):
            return True
        return super().Message(msg, result)

    def _set_busy(self, busy):
        self.busy = busy
        for identifier in (GENERATE, UPDATE, SAVE, REMOVE, EXPORT, IMPORT_LIBRARY,
                           EDIT_MODE) + _STYLE_CONTROLS:
            self.Enable(identifier, not busy)
        self.Enable(SPACE_FILL, not busy)
        self.Enable(BALL_STICK, not busy)
        self.Enable(CANCEL, busy)
        if self.editor is not None:
            self.HideElement(CANCEL, not busy)
            self.LayoutChanged(24)

    def _start(self, payload, operation, **extra):
        if operation == "resolve":
            self._close_atom_selector()
            self._show_records([], "resolve")
            self.SetString(SELECTED, "正在读取新结构…")
        # Keep C4D objects in a main-thread context, never inspect them in the worker.
        context = dict(operation=operation, document=c4d.documents.GetActiveDocument(), **extra)
        self.backend.submit(payload, context)
        self._set_busy(True)
        self._status("正在处理，可取消…")

    def _record(self):
        if not 0 <= self.selected < len(self.records):
            if self.current_record is not None:
                return validate_record(self.current_record)
            raise ValueError("请先选择结构图片")
        return validate_record(self.records[self.selected])

    def _get_style(self):
        style = copy.deepcopy(self.style)
        for identifier, key in ((ATOM_RADIUS, "atom_radius"),
                                (BOND_RADIUS, "bond_radius"), (SPACING, "bond_spacing")):
            style[key] = self.GetFloat(identifier)
        style["bond_mode"] = "multiple" if self.GetInt32(BOND_MODE) == 0 else "single"
        style["bond_material"] = "uniform" if self.GetInt32(BOND_MATERIAL) == 0 else "element"
        style["show_hydrogens"] = self.GetBool(HYDROGENS)
        style["quality"] = (12, 24, 36)[self.GetInt32(QUALITY)]
        color = self.GetColorField(BOND_COLOR)["color"]
        style["bond_color"] = [color.x, color.y, color.z]
        if style["representation"] == "ball_stick":
            style["ball_stick_radius"] = style["atom_radius"]
        return normalized_style(style)

    def _set_style(self, style):
        self.style = normalized_style(style)
        self.SetString(ATOM_LABEL, "球尺寸" if self.style["representation"] == "space_fill" else "球径")
        for identifier, key, limit in ((ATOM_RADIUS, "atom_radius", 3),
                                       (BOND_RADIUS, "bond_radius", 2), (SPACING, "bond_spacing", 3)):
            self.SetFloat(identifier, self.style[key], min=0.001, max=limit, step=0.01)
        self.SetInt32(BOND_MODE, 0 if self.style["bond_mode"] == "multiple" else 1)
        self.SetInt32(BOND_MATERIAL, 0 if self.style["bond_material"] == "uniform" else 1)
        self.SetBool(HYDROGENS, self.style["show_hydrogens"])
        self.SetInt32(QUALITY, (12, 24, 36).index(self.style["quality"]))
        self.SetColorField(BOND_COLOR, c4d.Vector(*self.style["bond_color"]),
                           1.0, 1.0, c4d.DR_COLORFIELD_NO_BRIGHTNESS)
        self.SetInt32(ELEMENT, 0)
        self._element_color()

    def _element_color(self):
        element = ELEMENTS[self.GetInt32(ELEMENT)]
        color = self.style["element_colors"].get(element, ELEMENT_COLORS[element])
        self.SetColorField(ELEMENT_COLOR, c4d.Vector(*color),
                           1.0, 1.0, c4d.DR_COLORFIELD_NO_BRIGHTNESS)

    def _show_records(self, records, view):
        if view == "resolve":
            self.current_record = None
        self.records = [validate_record(record) for record in records]
        self.view, self.page, self.selected = view, 0, -1
        self.SetString(SELECTED, "点击图片选择结构")
        self.SetString(WARNING, "")
        self._cards()
        self._status("共 %d 个结构" % len(self.records))

    def _refresh_lists(self):
        """Independent list switches; hiding both keeps the selected structure."""
        items = self.library.all()
        self.favorite_items = {item["record"]["structure_key"]: item for item in items}
        common = self.usage.ranked(self.builtins) if self.show_common else []
        favorites = []
        if self.show_favorites:
            for item in items:
                record = copy.deepcopy(item["record"])
                record["name"] = item["label"]
                record["list_source"] = "收藏"
                favorites.append(record)
        for record in common:
            record["list_source"] = "常用"
        combined = []
        for index in range(max(len(common), len(favorites))):
            if index < len(common): combined.append(common[index])
            if index < len(favorites): combined.append(favorites[index])
        if not self.show_common and not self.show_favorites:
            self.view = "library_hidden"
            if self.editor is not None:
                self.HideElement(14, True)
                self.HideElement(15, True)
                self.LayoutChanged(10)
            self._status("列表已收起")
        else:
            self._show_records(combined, "library")

    def _cards(self):
        if self.editor is not None:
            self.HideElement(14, False)
            self.HideElement(15, False)
        self.LayoutFlushGroup(CARDS)
        self.card_controls = []
        start = self.page * PAGE_SIZE
        visible = self.records[start:start + PAGE_SIZE]
        for offset, record in enumerate(visible):
            index = start + offset
            identifier = CARD_BASE + offset
            self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_TOP, cols=1)
            settings = c4d.BaseContainer()
            for symbol, value in ((c4d.BITMAPBUTTON_BUTTON, True), (c4d.BITMAPBUTTON_BORDER, False),
                                  (c4d.BITMAPBUTTON_NOBORDERDRAW, True), (c4d.BITMAPBUTTON_TOGGLE, True)):
                settings.SetBool(symbol, value)
            settings.SetInt32(c4d.BITMAPBUTTON_FORCE_SIZE, 128)
            settings.SetInt32(c4d.BITMAPBUTTON_FORCE_SIZE_Y, 100)
            detail = record["name"] + " · " + record.get("formula", "")
            if record.get("list_source"):
                detail += "<br>" + record["list_source"]
            if record.get("usage_count"):
                detail += " · 使用 %d 次" % record["usage_count"]
            settings.SetString(c4d.BITMAPBUTTON_TOOLTIP, detail)
            button = self.AddCustomGui(identifier, c4d.CUSTOMGUI_BITMAPBUTTON, record["name"],
                                       c4d.BFH_CENTER | c4d.BFV_FIXED, 128, 100, settings)
            if button and record.get("thumbnail"):
                button.SetImage(record["thumbnail"])
                button.SetToggleState(index == self.selected)
            self.card_controls.append(button)
            title = record["name"]
            self.AddButton(CARD_BASE + 100 + offset, c4d.BFH_SCALEFIT,
                           name=title if len(title) <= 13 else title[:12] + "…")
            if record.get("list_source"):
                self.AddStaticText(0, c4d.BFH_CENTER, name=record["list_source"])
            self.GroupEnd()
        if not visible:
            self.AddStaticText(0, c4d.BFH_LEFT, name="尚无结构")
        pages = max(1, (len(self.records) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.SetString(PAGE, "%d / %d" % (self.page + 1, pages))
        self.Enable(PREVIOUS, self.page > 0)
        self.Enable(NEXT, self.page + 1 < pages)
        self.LayoutChanged(CARDS)

    def _select(self, index):
        if not 0 <= index < len(self.records):
            return
        self.selected = index
        record = self._record()
        self.current_record = copy.deepcopy(record)
        item = self.favorite_items.get(record["structure_key"]) if (self.view == "favorites" or record.get("list_source") == "收藏") else None
        if item:
            self._set_style(item["style"])
        self.SetString(LABEL, item["label"] if item else record["name"])
        self.SetString(CATEGORY, item["category"] if item else "未分类")
        self.selected_text = record["name"] + " · " + record.get("formula", "")
        self.SetString(SELECTED, record["name"] if len(record["name"]) <= 20 else record["name"][:19] + "…")
        self.warning_text = "；".join(record.get("warnings", []))
        self.SetString(WARNING, self.warning_text if len(self.warning_text) <= 20 else "结构提示（悬停查看）")
        self._cards()
        self._status("已选择；可生成或收藏")
        if self.atom_selector and self.atom_selector.IsOpen() and record.get("thumbnail_atom_positions"):
            if record_integrity(self.atom_selector._record) != record_integrity(record):
                self._close_atom_selector()
            else:
                self.atom_selector.set_record(record)
        elif self.atom_selector:
            self._close_atom_selector()
        if not self._has_atom_preview(record):
            self._start({"action": "preview", "record": record}, "preview", index=index)

    @staticmethod
    def _has_atom_preview(record):
        path = record.get("thumbnail")
        return bool(record.get("depiction_version") == DEPICTION_VERSION and
                    isinstance(path, str) and os.path.isfile(path) and
                    record.get("thumbnail_atom_positions"))

    @staticmethod
    def _managed_selection(document):
        obj = document.GetActiveObject() if document else None
        while obj:
            if c4d_builder.is_managed(obj):
                return obj
            obj = obj.GetUp()
        return None

    def _build(self, record, style, document, replacement=None):
        record = validate_record(record, require_3d=True)
        if document != c4d.documents.GetActiveDocument():
            raise ValueError("当前场景已切换，请重新生成")
        root = c4d_builder.build_model(document, record, style, replace_root=replacement)
        usage_error = None
        if replacement is None:
            try:
                self.usage.record_use(record)
            except Exception as exc:
                usage_error = str(exc)
        if self.selector_root is not None and root != self.selector_root:
            self._close_atom_selector()
        self._show_records([record], "model")
        self._select(0)
        self._status("已生成 %d 个原子" % len(record["atoms"]) + ("；次数未保存：" + usage_error if usage_error else ""))
        c4d.EventAdd()

    def _close_atom_selector(self):
        selector = self.atom_selector
        if selector and getattr(selector, "groups_dirty", False) and self.selector_root is not None:
            # Keep drafts per actual model root, including two copies of the
            # same molecule. A structure digest alone cannot identify a scene.
            self.selector_drafts = [d for d in self.selector_drafts if d["root"] != self.selector_root]
            self.selector_drafts.append({"root": self.selector_root,
                                         "integrity": record_integrity(selector._record),
                                         "groups": copy.deepcopy(selector.groups)})
            self.selector_drafts = self.selector_drafts[-20:]
        if selector and selector.IsOpen():
            selector.Close()
        self.atom_selector = None
        self.selector_pending = False
        self.selector_root = None
        self._set_editor_visible(False)

    def _set_editor_visible(self, visible):
        if self.editor is not None:
            self.SetBool(EDIT_MODE, visible)
            self.HideElement(EDITOR_GROUP, not visible)
            self.LayoutChanged(ROOT_LAYOUT)

    def _open_atom_selector(self):
        root = self._managed_selection(c4d.documents.GetActiveDocument())
        if root is None:
            raise ValueError("请先生成并选中要调整的分子")
        if self.selector_root is not None and root != self.selector_root:
            self._close_atom_selector()
        record, style = c4d_builder.read_model(root)
        self._set_style(style)
        self._show_records([record], "model")
        self.selector_root = root
        self._select(0)
        if not self._has_atom_preview(self._record()):
            self.selector_pending = True
            self._status("正在准备二维原子选择图…")
            return
        self._open_atom_selector_ready()

    def _open_atom_selector_ready(self):
        from .atom_selector import AtomSelectionDialog
        self.selector_pending = False
        if self.atom_selector is None or not self.atom_selector.IsOpen():
            self.atom_selector = self.editor or AtomSelectionDialog(self._apply_flatten, self._restore_3d,
                                                                    self._select_model_atoms, self._apply_plane_groups)
            self.atom_selector.set_record(self._record())
            self.atom_selector.set_groups(self._get_style()["plane_groups"])
            draft = next((d for d in self.selector_drafts if d["root"] == self.selector_root and
                          d["integrity"] == record_integrity(self._record())), None)
            if draft is not None:
                self.atom_selector.set_groups(draft["groups"])
                self.atom_selector.groups_dirty = True
                self.atom_selector._status("分组待更新")
                self.selector_drafts.remove(draft)
            if self.editor is None:
                self.atom_selector.Open(c4d.DLG_TYPE_ASYNC, defaultw=450, defaulth=480)
        else:
            self.atom_selector.set_record(self._record())
        self._set_editor_visible(True)
        self._status("平面编辑已开启")

    def _flatten_target(self, local=False):
        document = c4d.documents.GetActiveDocument()
        root = self.selector_root if local else self._managed_selection(document)
        if root is None or not root.IsAlive() or root.GetDocument() != document:
            raise ValueError("请选中当前文档的分子，或重新打开二维选择")
        record, style = c4d_builder.read_model(root)
        record = validate_record(record, require_3d=True)
        if self.records and 0 <= self.selected < len(self.records):
            shown = self._record()
            if record_integrity(shown) == record_integrity(record):
                record = shown
        return document, root, record, normalized_style(style)

    def _apply_flatten(self, atom_ids=None, plane="auto"):
        try:
            if self.busy:
                raise ValueError("请等待当前结构处理完成")
            document, root, record, style = self._flatten_target(local=bool(self.selector_root))
            style["position_overrides"] = flatten_overrides(
                record, style["position_overrides"], atom_ids, plane)
            affected = set(atom_ids) if atom_ids is not None else {a["id"] for a in record["atoms"] if a["element"] != "H"}
            # Quick projection may change only part of a named plane. Remove
            # those members instead of displaying an inaccurate plane label.
            kept = {}
            for key, group in style["plane_groups"].items():
                group = copy.deepcopy(group)
                group["atom_ids"] = [i for i in group["atom_ids"] if i not in affected]
                if group["atom_ids"]:
                    kept[key] = group
            style["plane_groups"] = kept
            self._set_style(style)
            self._build(record, style, document, root)
            if self.atom_selector:
                self.atom_selector.set_groups(kept)
            self._status("已按二维展开；外围链段和氢跟随，可还原三维")
            return True
        except Exception as exc:
            self._error(exc)
            return False

    def _restore_3d(self):
        try:
            if self.busy:
                raise ValueError("请等待当前结构处理完成")
            document, root, record, style = self._flatten_target(local=bool(self.selector_root))
            style["position_overrides"] = {}
            style["plane_groups"] = {}
            self._set_style(style)
            self._build(record, style, document, root)
            self._status("已恢复原始三维坐标；材质和键显示模式保留")
            if self.atom_selector and self.atom_selector.IsOpen():
                self.atom_selector.set_groups({})
            return True
        except Exception as exc:
            self._error(exc)
            return False

    def _select_model_atoms(self, atom_ids):
        try:
            document, root, _record, _style = self._flatten_target(local=True)
            ids = set(atom_ids)
            selected = [o for o in c4d_builder._walk(root)
                        if o.CheckType(c4d.Oinstance) and re.fullmatch(r"原子_[A-Za-z]{1,2}_\d+", o.GetName())
                        and int(o.GetName().rsplit("_", 1)[1]) in ids]
            c4d.StopAllThreads()
            if selected:
                for index, obj in enumerate(selected):
                    document.SetActiveObject(obj, c4d.SELECTION_NEW if index == 0 else c4d.SELECTION_ADD)
            else:
                document.SetActiveObject(root, c4d.SELECTION_NEW)
            c4d.EventAdd()
        except Exception as exc:
            self._error(exc)

    def _apply_plane_groups(self, groups):
        try:
            if self.busy:
                raise ValueError("请等待当前结构处理完成")
            document, root, record, style = self._flatten_target(local=True)
            groups = normalized_plane_groups(groups)
            affected = {i for group in list(style["plane_groups"].values()) + list(groups.values()) for i in group["atom_ids"]}
            following = {b["b"] if b["a"] in affected else b["a"] for b in record["bonds"]
                         if (b["a"] in affected and record["atoms"][b["b"]]["element"] == "H")
                         or (b["b"] in affected and record["atoms"][b["a"]]["element"] == "H")}
            base = {key: xyz for key, xyz in style["position_overrides"].items() if int(key) not in affected | following}
            style["position_overrides"] = apply_plane_groups(record, groups, base)
            style["plane_groups"] = groups
            self._set_style(style)
            self._build(record, style, document, root)
            self.atom_selector.set_groups(groups)
            self._status("已更新 %d 个平面组；氢保留空间方向" % len(groups))
            return True
        except Exception as exc:
            self._error(exc)
            return False

    def _set_representation(self, representation):
        try:
            document, root, record, style = self._flatten_target()
            if representation == "space_fill":
                if style["representation"] == "ball_stick":
                    style["ball_stick_radius"] = style["atom_radius"]
                style["atom_radius"] = 1.0
            else:
                style["atom_radius"] = style["ball_stick_radius"]
            style["representation"] = representation
            self._set_style(style)
            self._build(record, style, document, root)
            self._status("已切换填充模型；允许球体交叠，可调整球尺寸" if representation == "space_fill" else "已切回球棍模型")
        except Exception as exc:
            self._error(exc)

    def Timer(self, msg):
        try:
            token, context, result, elapsed = self.backend.results.get_nowait()
        except queue.Empty:
            return
        if not self.alive or token != self.backend.generation:
            return
        self._set_busy(False)
        if context["document"] != c4d.documents.GetActiveDocument():
            self._status("场景已切换，本次结果已丢弃")
            return
        try:
            if not result.get("ok"):
                raise ValueError(result.get("error", "处理失败"))
            operation = context["operation"]
            if operation in ("resolve", "common"):
                records = result.get("records", [])
                if operation == "common":
                    self.builtins = copy.deepcopy(records)
                    self._refresh_lists()
                else:
                    self._show_records(records, operation)
            elif operation == "generate":
                self._build(result["record"], context["style"], context["document"], context.get("replacement"))
            elif operation == "preview":
                index = context["index"]
                if 0 <= index < len(self.records):
                    self.records[index] = validate_record(result["record"])
                    self._cards()
                    if self.selector_pending:
                        self._open_atom_selector_ready()
            self._status(self.GetString(STATUS) + "（%.1f 秒）" % elapsed)
        except Exception as exc:
            self._error(exc)

    def _error(self, exc):
        self._status(str(exc))
        if isinstance(exc, ValueError):
            Backend._log(f"{type(exc).__name__}: {exc}")
        else:
            Backend._log(traceback.format_exc())

    def Command(self, identifier, msg):
        try:
            if identifier in range(CARD_BASE, CARD_BASE + PAGE_SIZE):
                self.backend.cancel()
                self._set_busy(False)
                self._select(self.page * PAGE_SIZE + identifier - CARD_BASE)
            elif identifier in range(CARD_BASE + 100, CARD_BASE + 100 + PAGE_SIZE):
                self.backend.cancel()
                self._set_busy(False)
                self._select(self.page * PAGE_SIZE + identifier - CARD_BASE - 100)
            elif identifier == CANCEL:
                self.backend.cancel()
                self._set_busy(False)
                self._status("已取消")
            elif identifier in (RESOLVE, PASTE):
                if identifier == PASTE:
                    value = c4d.GetStringFromClipboard()
                    if not value:
                        raise ValueError("剪贴板没有文本，请在 ChemDraw 中复制为 SMILES")
                    self.SetString(INPUT, value.strip())
                    self.SetInt32(INPUT_KIND, 1)
                text = normalize_query_text(self.GetString(INPUT))
                if not text:
                    raise ValueError("请输入名称、分子式或 SMILES")
                kind = "smiles" if self.GetInt32(INPUT_KIND) == 1 else "name"
                if kind == "name" and is_valid_formula(text):
                    kind = "formula"
                self._start({"action": "resolve", "kind": kind, "text": text}, "resolve")
            elif identifier == IMPORT:
                path = c4d.storage.LoadDialog(title="选择 CDXML、MOL 或 SDF 文件")
                if path:
                    self._start({"action": "resolve", "kind": "file", "path": path}, "resolve")
            elif identifier == COMMON:
                self.backend.cancel()
                self._set_busy(False)
                self.show_common = self.GetBool(COMMON)
                if self.builtins or not self.show_common:
                    self._refresh_lists()
                else:
                    self._start({"action": "builtin"}, "common")
            elif identifier == FAVORITES:
                self.backend.cancel()
                self._set_busy(False)
                self.show_favorites = self.GetBool(FAVORITES)
                self._refresh_lists()
            elif identifier == READ_MODEL:
                document = c4d.documents.GetActiveDocument()
                root = self._managed_selection(document)
                if root is None:
                    raise ValueError("请在对象管理器中选择本工具生成的分子")
                editing = self.GetBool(EDIT_MODE)
                if self.selector_root is not None and root != self.selector_root:
                    self._close_atom_selector()
                record, style = c4d_builder.read_model(root)
                self._set_style(style)
                self._show_records([record], "model")
                self._select(0)
                if editing:
                    self._open_atom_selector()
            elif identifier in (PREVIOUS, NEXT):
                self.page += -1 if identifier == PREVIOUS else 1
                self._cards()
            elif identifier == ELEMENT:
                self._element_color()
            elif identifier == FLATTEN_ALL:
                self._apply_flatten(plane=("auto", "xy", "xz", "yz")[self.GetInt32(FLATTEN_PLANE)])
            elif identifier == ATOM_SELECT:
                self._open_atom_selector()
            elif identifier == EDIT_MODE:
                if self.GetBool(EDIT_MODE):
                    try:
                        self._open_atom_selector()
                    except Exception:
                        self._set_editor_visible(False)
                        raise
                else:
                    self.selector_pending = False
                    self._set_editor_visible(False)
            elif identifier == RESTORE_3D:
                self._restore_3d()
            elif identifier in (SPACE_FILL, BALL_STICK):
                self._set_representation("space_fill" if identifier == SPACE_FILL else "ball_stick")
            elif identifier == APPLY_COLOR:
                element = ELEMENTS[self.GetInt32(ELEMENT)]
                color = self.GetColorField(ELEMENT_COLOR)["color"]
                self.style["element_colors"][element] = [color.x, color.y, color.z]
                self._status("已设置球 " + element + " 的颜色；点击生成或更新应用")
            elif identifier in (GENERATE, UPDATE):
                document = c4d.documents.GetActiveDocument()
                replacement = self._managed_selection(document) if identifier == UPDATE else None
                if identifier == UPDATE:
                    if replacement is None:
                        raise ValueError("请先选中要更新的分子根对象或其子对象")
                    record = validate_record(c4d_builder.read_model(replacement)[0], require_3d=True)
                else:
                    record = self._record()
                style = self._get_style()
                if record.get("has_3d") and record.get("coordinates_ready"):
                    self._build(record, style, document, replacement)
                else:
                    self._start({"action": "generate", "record": record}, "generate", style=style, replacement=replacement)
            elif identifier == SAVE:
                record = self._record()
                self.library.save(record, self._get_style(), self.GetString(LABEL), self.GetString(CATEGORY))
                if self.show_favorites:
                    self._refresh_lists()
                    selected = next((i for i, r in enumerate(self.records) if r.get("list_source") == "收藏" and r["structure_key"] == record["structure_key"]), None)
                    if selected is not None:
                        self._select(selected)
                self._status("已保存到本地收藏；重复结构更新当前预设")
            elif identifier == REMOVE:
                record = self._record()
                if record["structure_key"] not in {i["record"]["structure_key"] for i in self.library.all()}:
                    raise ValueError("请先选择收藏条目")
                self.library.remove(record["structure_key"])
                self._refresh_lists()
            elif identifier == EXPORT:
                path = c4d.storage.SaveDialog(title="导出收藏", force_suffix="json")
                if path:
                    self.library.export_to(path)
                    self._status("收藏已导出")
            elif identifier == IMPORT_LIBRARY:
                path = c4d.storage.LoadDialog(title="导入收藏 JSON")
                if path:
                    count = self.library.import_from(path)
                    self._refresh_lists()
                    self._status("已新增 %d 个收藏，已有结构保留" % count)
            elif identifier == DETAILS:
                record = self._record()
                text = (record["name"] + "\n" + record.get("formula", "") +
                        "\nSMILES: " + record["smiles"] + "\n" +
                        "\n".join(record.get("warnings", [])) +
                        "\n\n出品：与可 | YUKE (DeepLeap)")
                c4d.gui.MessageDialog(text)
        except Exception as exc:
            self._error(exc)
        return True

    def DestroyWindow(self):
        self._close_atom_selector()
        self.alive = False
        getattr(self.backend, "close", self.backend.cancel)()
        self.SetTimer(0)
        if getattr(builtins, "_scimol_native_dialog_v1", None) is self:
            builtins._scimol_native_dialog_v1 = None


def run(doc=None):
    existing = getattr(builtins, "_scimol_native_dialog_v1", None)
    if existing is not None and existing.IsOpen():
        return True
    from .browser_ui import BrowserDialog
    dialog = BrowserDialog()
    builtins._scimol_native_dialog_v1 = dialog
    return dialog.Open(c4d.DLG_TYPE_ASYNC, defaultw=1120, defaulth=720)
