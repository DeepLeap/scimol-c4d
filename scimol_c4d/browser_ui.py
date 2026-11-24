"""Native resource browsing and a single explicitly bound adjustment target."""
import copy
import os
import queue
import re
import time

import c4d
from . import ui as legacy
from .ui import *
from .records import DEPICTION_VERSION, PREVIEW_FIELDS, stable_json, migrate_element_scales
from .search_index import suggest_names, rank_local_names, normalize_query_text, smart_input_hint
from .native_ui import add_action, add_brand_logo, hover_help, set_action_active
from .appearance_scale import to_display, to_physical
from .floating_windows import WindowFollower, editor_open_position

SMILES_INPUT, CONFIRM = 1501, 1502
LEFT_TOGGLE, RIGHT_TOGGLE, NEW_FOLDER, MORE = 1510, 1511, 1512, 1513
FOLDER_TREE, THUMBNAILS, LIBRARY_GROUP, ADJUST_GROUP, SUGGEST_GROUP = 1520, 1521, 1522, 1523, 1524
SPHERE_SEGMENTS, CYLINDER_SEGMENTS, BOND_ELEMENT = 1530, 1531, 1532
SIZE_ELEMENT, ELEMENT_SIZE_ENABLE, ELEMENT_SIZE, ELEMENT_SIZE_SLIDER = 1533, 1534, 1535, 1536
CONFIG_SAVE, CONFIG_SAVE_AS, RESET = 1550, 1551, 1552
DELETE_SELECTED = 1553
FINISH, BOND_CAPS, MATERIAL_INHERIT, SEARCH_STATUS = 1554, 1555, 1556, 1557
PASTE_SEARCH, STICK_MODE, COLOR_PRESET, REBIND_ACTIVE, BRAND_LOGO = 1560, 1561, 1562, 1563, 1564
ATOM_SLIDER, BOND_SLIDER, SPACING_SLIDER, SPHERE_SLIDER, CYLINDER_SLIDER = 1540, 1541, 1542, 1543, 1544
SLIDER_RESETS = {ATOM_SLIDER:1700, SPHERE_SLIDER:1701, ELEMENT_SIZE_SLIDER:1702,
                 BOND_SLIDER:1703, CYLINDER_SLIDER:1704, SPACING_SLIDER:1705}
RESET_SLIDERS = {button:slider for slider, button in SLIDER_RESETS.items()}
SUGGEST_BASE = 1600
COLOR_PRESETS = (
    ("配色：当前／默认", None),
    ("经典 CPK", {"elements": ELEMENT_COLORS, "bond_color": list(DEFAULT_STYLE["bond_color"])}),
    ("Nature 银灰学术", {
        "elements": {
            "C": [0.32, 0.35, 0.39], "H": [0.95, 0.96, 0.98],
            "O": [0.88, 0.26, 0.24], "N": [0.22, 0.45, 0.82],
            "S": [0.92, 0.72, 0.20], "P": [0.90, 0.48, 0.18],
            "F": [0.36, 0.74, 0.56], "Cl": [0.25, 0.66, 0.46],
            "Br": [0.64, 0.26, 0.22], "I": [0.52, 0.32, 0.68],
        },
        "bond_color": [0.76, 0.78, 0.82],
    }),
    ("Science 冷调晶体", {
        "elements": {
            "C": [0.20, 0.25, 0.32], "H": [0.90, 0.95, 0.99],
            "O": [0.85, 0.18, 0.36], "N": [0.16, 0.56, 0.88],
            "S": [0.94, 0.76, 0.24], "P": [0.88, 0.44, 0.26],
            "F": [0.26, 0.82, 0.72], "Cl": [0.18, 0.72, 0.60],
            "Br": [0.60, 0.22, 0.34], "I": [0.48, 0.28, 0.76],
        },
        "bond_color": [0.68, 0.74, 0.82],
    }),
    ("明快白底插图", {
        "elements": {
            "C": [0.42, 0.44, 0.47], "H": [0.97, 0.97, 0.98],
            "O": [0.92, 0.31, 0.28], "N": [0.24, 0.52, 0.90],
            "S": [0.95, 0.77, 0.18], "P": [0.94, 0.52, 0.20],
            "F": [0.35, 0.80, 0.50], "Cl": [0.26, 0.74, 0.42],
            "Br": [0.70, 0.30, 0.22], "I": [0.56, 0.34, 0.74],
        },
        "bond_color": [0.82, 0.84, 0.86],
    }),
    ("与可竹青（品牌）", {
        "elements": {
            "C": [0.16, 0.20, 0.26], "H": [0.97, 0.98, 0.99],
            "O": [0.86, 0.26, 0.25], "N": [0.06, 0.46, 0.43],
            "S": [0.91, 0.72, 0.22], "P": [0.89, 0.47, 0.20],
            "F": [0.18, 0.83, 0.75], "Cl": [0.12, 0.65, 0.58],
            "Br": [0.62, 0.24, 0.24], "I": [0.46, 0.30, 0.68],
        },
        "bond_color": [0.74, 0.78, 0.82],
    }),
)
PAIRS = ((ATOM_RADIUS, ATOM_SLIDER, "atom_radius", 1., 5.),
         (BOND_RADIUS, BOND_SLIDER, "bond_radius", 1., 5.),
         (SPACING, SPACING_SLIDER, "bond_spacing", 1., 5.),
         (SPHERE_SEGMENTS, SPHERE_SLIDER, "sphere_segments", 8, 64),
         (CYLINDER_SEGMENTS, CYLINDER_SLIDER, "cylinder_segments", 8, 64))
LIVE_CONTROLS = {ATOM_RADIUS, BOND_RADIUS, SPACING, SPHERE_SEGMENTS,
                 CYLINDER_SEGMENTS, BOND_MODE, BOND_MATERIAL, HYDROGENS,
                 ELEMENT_COLOR, BOND_COLOR, LABEL, BOND_CAPS, MATERIAL_INHERIT}


class BrowserDialog(legacy.MoleculeDialog):
    def __init__(self):
        super().__init__()
        self.bound_root = None
        self.session_active = False
        self._session_document = None
        self._seen_active = None
        self._live_due = None
        self._poll_due = 0.
        self.left_visible = True
        self.right_visible = False
        self.editing = False
        self.icon_controls = {}
        self.selected_cards = set()
        self.folder_tree = self.thumbnail_area = None
        self.folder_current = "common"
        self.folder_nodes = []
        self.suggestions = []
        self._suggestion_actions = []
        self.preview_backend = Backend()
        self._preview_pending = False
        self._ready_records = {}
        self._foreground_operation = None
        self.search_pending = False
        self.search_message = ""
        self.search_records = []
        self._resolve_cache = {}
        self._preview_cache = {}
        self._search_pulse = 0
        self._search_pulse_due = 0.
        self._last_model_style = None
        self._usage_key = None
        self.available_elements = ()
        self.size_elements = ()
        self._window_follower = WindowFollower()
        self._follow_retry_due = 0.
        self.configuration_id = None
        self.preset_origin_record = None
        self.pane_weights = {LIBRARY_GROUP: 40., ADJUST_GROUP: 27., EDITOR_GROUP: 33.}
        self._rebuild_folders()

    def CreateLayout(self):
        from .browser_layout import build
        return build(self, __import__(__name__, fromlist=["*"]))

    def InitValues(self):
        self.SetInt32(COLOR_PRESET, 0)
        self._set_style(self.style)
        self._set_pane_weights()
        self.editor.set_editing(False)
        self.HideElement(CANCEL, True)
        self.SetTimer(40)
        self._start({"action": "builtin"}, "common")
        return True

    def _record(self):
        if self.current_record is not None:
            return validate_record(self.current_record)
        return super()._record()

    def _toggle_icon(self, identifier, state):
        control = self.icon_controls.get(identifier)
        if control: control.SetToggleState(bool(state))

    def _set_pane_weights(self):
        visible = [LIBRARY_GROUP, ADJUST_GROUP]
        total = sum(self.pane_weights[i] for i in visible)
        weights = c4d.BaseContainer()
        weights.SetInt32(c4d.GROUPWEIGHTS_PERCENT_W_CNT, 2)
        for i in range(2):
            weights.SetFloat(c4d.GROUPWEIGHTS_PERCENT_W_VAL+i,
                             self.pane_weights[visible[i]]*100./total if i < len(visible) else 0.)
        self.GroupWeightsLoad(ROOT_LAYOUT, weights)

    def _remember_pane_weights(self):
        weights = self.GroupWeightsSave(ROOT_LAYOUT)
        if not weights: return
        visible = [LIBRARY_GROUP, ADJUST_GROUP]
        original_total = sum(self.pane_weights[i] for i in visible)
        values = [max(.001, weights.GetFloat(c4d.GROUPWEIGHTS_PERCENT_W_VAL+i)) for i in range(len(visible))]
        for group, value in zip(visible, values): self.pane_weights[group] = value/sum(values)*original_total

    def _set_busy(self, busy):
        self.busy = busy
        # Chemistry runs off-thread; adjustments stay available while loading.
        for identifier in LIVE_CONTROLS | {GENERATE, SAVE, EDIT_MODE}:
            self.Enable(identifier, True)
        self.Enable(FINISH, self.session_active)
        self.HideElement(CANCEL, not busy)
        self.LayoutChanged(25)

    def _get_style(self):
        style = copy.deepcopy(self.style)
        for number, slider, key, low, high in PAIRS:
            if "segments" in key:
                style[key] = self.GetInt32(number)
            else:
                display = round(self.GetFloat(number), 1)
                # Loading an older precise physical value must not quantize it.
                if display != round(to_display(key, self.style[key]), 1):
                    style[key] = to_physical(key, display)
        style["bond_mode"] = "multiple" if self.GetBool(BOND_MODE) else "single"
        style["bond_material"] = "uniform" if self.GetBool(BOND_MATERIAL) else "element"
        style["show_hydrogens"] = self.GetBool(HYDROGENS)
        style["bond_caps"] = self.GetBool(BOND_CAPS)
        style["inherit_materials"] = self.GetBool(MATERIAL_INHERIT)
        if style["representation"] == "ball_stick":
            style["ball_stick_radius"] = style["atom_radius"]
        return normalized_style(style)

    def _set_style(self, style):
        atom_index = self.GetInt32(ELEMENT)
        bond_index = self.GetInt32(BOND_ELEMENT)
        self.style = migrate_element_scales(style)
        for number, slider, key, low, high in PAIRS:
            value = self.style[key]
            if "segments" in key:
                self.SetInt32(number, value, min=3, max=512)
                self.SetInt32(slider, min(high, max(low, value)), min=low, max=high)
            else:
                self._set_size_pair(number, slider, to_display(key, value), low, high)
        self.SetBool(BOND_MODE, self.style["bond_mode"] == "multiple")
        self.SetBool(BOND_MATERIAL, self.style["bond_material"] == "uniform")
        self.SetBool(HYDROGENS, self.style["show_hydrogens"])
        self.SetBool(BOND_CAPS, self.style.get("bond_caps", True))
        self.SetBool(MATERIAL_INHERIT, self.style.get("inherit_materials", True))
        self.SetInt32(ELEMENT, max(0, min(len(self.available_elements)-1, atom_index)))
        self.SetInt32(BOND_ELEMENT, max(0, min(len(self.available_elements)-1, bond_index)))
        self._element_color()
        self._element_size()
        self._bond_color()
        self._toggle_icon(BALL_STICK, self.style["representation"] == "ball_stick")
        self._toggle_icon(SPACE_FILL, self.style["representation"] == "space_fill")
        self._update_smart_controls()
        if self.editor:
            self.editor.set_appearance(self.style)
            if hasattr(self.editor, "set_orientation"): self.editor.set_orientation(self.style)

    def _update_smart_controls(self):
        is_fill = self.style.get("representation") == "space_fill"
        bond_ui = not is_fill
        if self.current_record is None:
            has_multiple_bonds = True
            has_hydrogens = True
        else:
            bonds = self.current_record.get("bonds") or []
            has_multiple_bonds = any(
                b.get("aromatic") or float(b.get("order", 1)) > 1.0 for b in bonds
            )
            atoms = self.current_record.get("atoms") or []
            has_hydrogens = (
                any(a.get("element") == "H" for a in atoms)
                or bool(re.search(r"H(?![a-z])", str(self.current_record.get("formula", ""))))
            )
        for identifier in (
            BOND_RADIUS, BOND_SLIDER, SLIDER_RESETS[BOND_SLIDER],
            CYLINDER_SEGMENTS, CYLINDER_SLIDER, SLIDER_RESETS[CYLINDER_SLIDER],
            BOND_CAPS, BOND_MATERIAL,
        ):
            self.Enable(identifier, bond_ui)
        self.Enable(BOND_MODE, bond_ui and has_multiple_bonds)
        spacing_enabled = bond_ui and has_multiple_bonds and self.style.get("bond_mode") == "multiple"
        for identifier in (SPACING, SPACING_SLIDER, SLIDER_RESETS[SPACING_SLIDER]):
            self.Enable(identifier, spacing_enabled)
        self.Enable(BOND_ELEMENT, bond_ui and bool(self.available_elements) and self.style.get("bond_material") != "uniform")
        self.Enable(BOND_COLOR, bond_ui and bool(self.available_elements))
        self.Enable(HYDROGENS, has_hydrogens)
        can_rebind = (not self.session_active and
                      self._managed_selection(c4d.documents.GetActiveDocument()) is not None)
        self.Enable(REBIND_ACTIVE, can_rebind)

    def _element_color(self):
        element = self._chosen_element(ELEMENT)
        color = self.style["element_colors"].get(element, ELEMENT_COLORS.get(element, [.5, .5, .5]))
        self.SetColorField(ELEMENT_COLOR, c4d.Vector(*color), 1., 1., c4d.DR_COLORFIELD_NO_BRIGHTNESS)
        self.Enable(ELEMENT, bool(element))
        self.Enable(ELEMENT_COLOR, bool(element))

    def _set_size_pair(self, number, slider, value, low=1., high=5.):
        value = round(float(value), 1)
        self.SetFloat(number, value, min=.1, max=1000000., step=.1)
        self.SetFloat(slider, min(high, max(low, value)), min=low, max=high, step=.1)

    def _chosen_element(self, identifier):
        if not self.available_elements: return None
        index = max(0, min(len(self.available_elements)-1, self.GetInt32(identifier)))
        return self.available_elements[index]

    def _size_element(self):
        return self._chosen_element(SIZE_ELEMENT)

    def _refresh_size_elements(self):
        chosen = {identifier:self._chosen_element(identifier)
                  for identifier in (ELEMENT, BOND_ELEMENT, SIZE_ELEMENT)}
        available = {atom["element"] for atom in (self.current_record or {}).get("atoms", [])}
        elements = tuple(e for e in ELEMENTS if e in available) + tuple(sorted(available - set(ELEMENTS)))
        if elements != self.available_elements:
            self.available_elements = elements
            self.size_elements = elements
            for identifier, element in chosen.items():
                if hasattr(self, "FreeChildren"):
                    self.FreeChildren(identifier)
                    for index, item in enumerate(elements): self.AddChild(identifier, index, item)
                self.SetInt32(identifier, elements.index(element) if element in elements else 0)
        self._element_color()
        self._bond_color()
        self._element_size()
        self._update_smart_controls()

    def _element_size(self):
        element = self._size_element()
        factor = self.style.get("element_scales", {}).get(element, 1.)
        self._set_size_pair(ELEMENT_SIZE, ELEMENT_SIZE_SLIDER, factor, .1, 3.)
        for identifier in (SIZE_ELEMENT, ELEMENT_SIZE, ELEMENT_SIZE_SLIDER,
                           SLIDER_RESETS[ELEMENT_SIZE_SLIDER]):
            self.Enable(identifier, bool(element))

    def _bond_color(self):
        uniform = self.style["bond_material"] == "uniform"
        element = self._chosen_element(BOND_ELEMENT)
        color = self.style["bond_color"] if uniform else self.style["bond_element_colors"].get(element, ELEMENT_COLORS.get(element, [.5, .5, .5]))
        self.SetColorField(BOND_COLOR, c4d.Vector(*color), 1., 1., c4d.DR_COLORFIELD_NO_BRIGHTNESS)
        self.Enable(BOND_ELEMENT, bool(element) and not uniform)
        self.Enable(BOND_COLOR, bool(element))

    def _rebuild_folders(self):
        folders = [name for name in self.library.folders() if name != "未分类"]
        if self.folder_current == "folder:未分类": self.folder_current = "all"
        self.folder_nodes = [{"id":"common","name":"常用","parent":None,"children":[]},
                             {"id":"all","name":"全部","parent":None,"children":[]},
                             {"id":"favorites","name":"收藏","parent":None,
                              "children":["folder:"+name for name in folders]}]
        for name in folders:
            self.folder_nodes.append({"id":"folder:"+name,"name":name,"parent":"favorites","children":[]})
        if self.folder_current == "search":
            self.folder_nodes.append({"id":"search","name":"搜索结果","parent":None,"children":[]})
        if self.folder_tree: self.folder_tree.Refresh()

    def _folder_records(self, folder):
        items = self.library.all()
        self.favorite_items = {item["id"]: item for item in items}
        favorites = []
        for item in items:
            if folder.startswith("folder:") and item["category"] != folder.removeprefix("folder:"): continue
            record = copy.deepcopy(item["record"])
            record["name"] = item["label"]; record["list_source"] = "收藏"
            favorites.append(record)
        if folder in ("common", "all"):
            records = self.usage.ranked([*self.builtins, *favorites])
            if folder == "all":
                records.sort(key=lambda r: (r["name"].casefold(), self._resource_key(r)))
            return records
        return favorites

    @staticmethod
    def _resource_key(record):
        return record.get("configuration_id") or record["structure_key"]

    def _refresh_browser_records(self):
        """Refresh the folder while leaving the active adjustment target intact."""
        if self.folder_current == "search": return
        selected = {self._resource_key(self.records[i]) for i in self.selected_cards
                    if 0 <= i < len(self.records)}
        self.records = [self._cached_preview(r) for r in self._folder_records(self.folder_current)]
        self.selected_cards = {i for i, record in enumerate(self.records)
                               if self._resource_key(record) in selected}
        active = self._resource_key(self.current_record) if self.current_record else None
        self.selected = next((i for i, record in enumerate(self.records)
                              if self._resource_key(record) == active), -1)
        self._cards()

    def _browse_folder(self, folder):
        self.folder_current = "all" if folder == "folder:未分类" else folder
        if folder == "search":
            self._show_records(self.search_records, "resolve")
            return
        records = self._folder_records(self.folder_current)
        self._show_records(records, folder)
        if self.folder_tree: self.folder_tree.Refresh()

    def _refresh_lists(self):
        self._rebuild_folders()
        self._browse_folder(self.folder_current)

    def _show_records(self, records, view):
        records = [self._cached_preview(record) for record in records]
        if view == "resolve": self.search_records = copy.deepcopy(records)
        if self.session_active:
            # Folder/search browsing changes only the library, never commits
            # or detaches the model being edited.
            self.records = [validate_record(r) for r in records]
            self.view = view
            key = self._resource_key(self.current_record) if self.current_record else None
            self.selected = next((i for i,r in enumerate(self.records)
                                  if self._resource_key(r) == key), -1)
            self.selected_cards = {self.selected} if self.selected >= 0 else set()
            if view == "resolve":
                self.folder_current = "search"; self._rebuild_folders()
            self._cards()
            self._status("选择结构替换当前预览")
            self._refresh_missing_previews()
            return
        self._finish_session()
        self._close_atom_selector()
        self.current_record = None
        self.bound_root = None
        self._seen_active = self._managed_selection(c4d.documents.GetActiveDocument())
        self.SetString(LABEL, "")
        self.SetString(SELECTED, "选择一个结构")
        self.Enable(GENERATE, False)
        self.configuration_id = None
        self.preset_origin_record = None
        if self.editor:
            self.editor.selected_ids.clear()
            self.editor.selected_bonds.clear()
            self.editor.groups_dirty = False
            self.editor.groups = {}
            self.editor._image.bitmap = None
            self.editor._image.light_bitmap = None
            self.editor._image.dark_bitmap = None
            self.editor._image.positions = {}
            self.editor._image.bonds = {}
            self.editor.set_appearance(DEFAULT_STYLE)
            self.editor._image.Redraw()
        self.records = [validate_record(r) for r in records]
        self.view = view; self.selected = -1
        self.selected_cards = set()
        if view == "resolve":
            self.folder_current = "search"; self._rebuild_folders()
        self._cards()
        self._status("%d 个结构" % len(self.records))
        self._refresh_missing_previews()

    def _refresh_missing_previews(self):
        if self._preview_pending: return
        missing = [r for r in self.records if not self._has_theme(r)][:24]
        if missing:
            self._start({"action": "previews", "records": missing}, "themes", view=self.view)

    @staticmethod
    def _copy_preview(target, source):
        for field in PREVIEW_FIELDS:
            if field in source:
                target[field] = copy.deepcopy(source[field])

    def _cached_preview(self, record):
        record = copy.deepcopy(record)
        preview = self._preview_cache.get(record_integrity(record))
        if preview:
            self._copy_preview(record, preview)
        return record

    def _remember_previews(self, records):
        previews = {record_integrity(record): record for record in records
                    if record.get("depiction_version") == DEPICTION_VERSION}
        if not previews:
            return
        for key, record in previews.items():
            self._preview_cache.pop(key, None)
            self._preview_cache[key] = {field: copy.deepcopy(record[field])
                                        for field in PREVIEW_FIELDS if field in record}
        while len(self._preview_cache) > 200:
            self._preview_cache.pop(next(iter(self._preview_cache)))
        collections = [self.records, self.builtins, self.search_records,
                       *self._resolve_cache.values(), list(self._ready_records.values())]
        for collection in collections:
            for record in collection:
                preview = previews.get(record_integrity(record))
                if preview:
                    self._copy_preview(record, preview)
        if self.current_record:
            preview = previews.get(record_integrity(self.current_record))
            if preview:
                self._copy_preview(self.current_record, preview)
                self._display(self.current_record)

    def _cards(self):
        if self.thumbnail_area:
            self.thumbnail_area.Redraw()
            self.LayoutChanged(CARDS)

    def _display(self, record):
        self.current_record = validate_record(record)
        self._refresh_size_elements()
        self.Enable(FINISH, self.session_active)
        self._update_smart_controls()
        self.SetString(LABEL, record["name"])
        self.selected_text = record["name"] + " · " + record.get("formula", "")
        self.SetString(SELECTED, record.get("formula", ""))
        self.warning_text = "；".join(record.get("warnings", []))
        self.SetString(WARNING, "结构提示（悬停查看）" if self.warning_text else "")
        if self.editor and self._has_atom_preview(record):
            self.editor.set_record(record)
            self.editor.set_appearance(self.style)
            if not self.editor.groups_dirty:
                self.editor.set_groups(self.style["plane_groups"])
            self._set_editor_visible(self.right_visible)
            if self.right_visible: self.atom_selector = self.editor

    def _select(self, index, generate=True):
        if not 0 <= index < len(self.records): return False
        record = validate_record(self.records[index])
        if (generate and self.session_active and self.current_record and
                self._resource_key(record) == self._resource_key(self.current_record) and
                record["name"] == self.current_record["name"] and
                (self.current_record.get("coordinates_ready") or
                 self.busy and self._foreground_operation in ("asset", "generate"))):
            self.selected = index; self.selected_cards = {index}
            return True
        replacement = self.bound_root if self._binding_valid() else None
        if generate and self.bound_root is not None and replacement is None:
            self._finish_session(flush=False)
        self.selected_cards = {index}
        self.backend.cancel(); self._set_busy(False)
        self.preview_backend.cancel(); self._preview_pending = False
        self._live_due = None
        if self.editor:
            self.editor.groups_dirty = False
            self.editor.selected_ids.clear(); self.editor.selected_bonds.clear()
        self.bound_root = replacement
        self._seen_active = self._managed_selection(c4d.documents.GetActiveDocument())
        self.selected = index
        source_key = record_integrity(record)
        cached = self._ready_records.get(source_key)
        if cached and not record.get("coordinates_ready"):
            geometry = copy.deepcopy(cached)
            for field in ("name", "source", "configuration_id", "list_source", "usage_count"):
                if field in record: geometry[field] = copy.deepcopy(record[field])
                else: geometry.pop(field, None)
            record = validate_record(geometry)
            self.records[index] = copy.deepcopy(record)
        item = self.favorite_items.get(record.get("configuration_id") or record["structure_key"]) if record.get("configuration_id") or record.get("list_source") == "收藏" else None
        self.configuration_id = item["id"] if item and item.get("type") == "configuration" else None
        self.preset_origin_record = copy.deepcopy(record)
        self.session_active = bool(generate)
        self._session_document = c4d.documents.GetActiveDocument() if generate else None
        style = copy.deepcopy(item["style"] if item else DEFAULT_STYLE)
        if not item:
            style["representation"] = "continuous"
            if hasattr(c4d_builder, "inherited_style"):
                style = c4d_builder.inherited_style(c4d.documents.GetActiveDocument(), record, style)
        self._set_style(style)
        self.SetInt32(COLOR_PRESET, 0)
        self._display(record); self._cards()
        if record.get("coordinates_ready") and record.get("has_3d"):
            if generate: self._apply_current()
            if not self._has_theme(record): self._start({"action":"preview","record":record}, "theme", structure_key=record["structure_key"])
        else:
            self._start({"action":"generate","record":record}, "asset",
                        structure_key=record["structure_key"], resource_key=self._resource_key(record),
                        source_key=source_key)
        return True

    def _start(self, payload, operation, **extra):
        if operation == "resolve":
            extra["query"] = str(payload.get("text", "")).strip()
        context = dict(operation=operation, document=c4d.documents.GetActiveDocument(), **extra)
        if operation in ("themes", "theme", "preview"):
            if self.current_record:
                context["resource_key"] = self._resource_key(self.current_record)
            if operation in ("theme", "preview"):
                context["source_integrity"] = record_integrity(payload["record"])
            self.preview_backend.submit(payload, context)
            self._preview_pending = True
        else:
            self._foreground_operation = operation
            if operation == "resolve":
                self.search_pending = True
                self.search_message = "正在搜索…"
                self._search_pulse = 0
                self._search_pulse_due = 0.
                self.SetString(SEARCH_STATUS, self.search_message)
                self.folder_current = "search"
                self.records = []; self.selected_cards = set(); self.selected = -1
                self.search_records = []
                self.view = "resolve"
                self._rebuild_folders(); self._cards()
            elif self.search_pending:
                self._end_search("搜索已取消")
            self.backend.submit(payload, context)
            self._set_busy(True)
            self._status("正在读取结构…" if operation == "resolve" else "正在准备结构…")

    def _end_search(self, message):
        self.search_pending = False
        self.search_message = message
        self.SetString(SEARCH_STATUS, message)
        self._cards()

    def _cache_search(self, query, records):
        if not query or not records: return
        self._resolve_cache.pop(query, None)
        self._resolve_cache[query] = copy.deepcopy(records)
        if len(self._resolve_cache) > 100:
            self._resolve_cache.pop(next(iter(self._resolve_cache)))

    def _search(self, text):
        text = normalize_query_text(text)
        if not text:
            raise ValueError("请输入名称、分子式或 SMILES")
        # Exact keys preserve SMILES case. Cache only original search records,
        # never the active renamed resource or its user-adjusted display style.
        records = self._resolve_cache.get(text)
        if not records:
            ranked = rank_local_names(text)
            by_name = {record["name"]: record for record in self.builtins}
            if ranked and all(name in by_name for name in ranked):
                records = [by_name[name] for name in ranked]
            elif not ranked:
                records = [record for record in self.builtins if record.get("smiles") == text]
        if records:
            if self._foreground_operation == "resolve":
                self.backend.cancel(); self._foreground_operation = None; self._set_busy(False)
            self._cache_search(text, records)
            self._end_search("找到 %d 个结构 · 本地" % len(records))
            self._show_records(copy.deepcopy(records), "resolve")
            return
        self._start({"action":"resolve", "kind":"auto", "text":text}, "resolve")

    def _set_editor_visible(self, visible):
        self.editing = bool(visible)
        self.right_visible = bool(visible)
        details = getattr(self, "details_control", None)
        if details: set_action_active(self, RIGHT_TOGGLE, self.right_visible)
        control = getattr(self, "edit_control", None)
        if control: control.SetToggleState(self.editing)
        if self.editor: self.editor.set_editing(self.editing)

    def _details_closed(self):
        self._window_follower.stop()
        self._set_editor_visible(False)

    def _close_atom_selector(self):
        self._window_follower.stop()
        if self.editor and self.editor.IsOpen(): self.editor.Close()
        self.atom_selector = None
        self.selector_pending = False
        self.selector_root = None
        self._set_editor_visible(False)

    def _open_atom_selector(self):
        if self.current_record is None: raise ValueError("请先选择结构")
        if not self._has_atom_preview(self._record()):
            self.selector_pending = True
            self._start({"action":"preview","record":self._record()}, "preview", structure_key=self._record()["structure_key"])
            return
        self._open_atom_selector_ready()

    def _open_atom_selector_ready(self):
        self.selector_pending = False
        self.atom_selector = self.editor
        self.atom_selector.set_record(self._record())
        if not self.atom_selector.groups_dirty:
            self.atom_selector.set_groups(self.style["plane_groups"])
        self.selector_root = self.bound_root
        if not self.editor.IsOpen():
            position = editor_open_position(self)
            options = {"defaultw": 520, "defaulth": 680}
            if position is not None:
                options.update(xpos=position[0], ypos=position[1])
            if not self.editor.Open(c4d.DLG_TYPE_ASYNC, **options):
                raise ValueError("无法打开结构详情")
        self._set_editor_visible(True)
        self._window_follower.start(self, self.editor)
        self._follow_retry_due = time.monotonic() + 1.

    def _binding_valid(self):
        root = self.bound_root
        document = c4d.documents.GetActiveDocument()
        return bool(self.session_active and root is not None and root.IsAlive() and
                    root.GetDocument() == document and self._session_document == document)

    def _bind_root(self, root):
        changed = self.bound_root != root
        if changed:
            if self.editor: self.editor.groups_dirty = False
        record, style = c4d_builder.read_model(root)
        self.configuration_id = record.get("configuration_id")
        self.preset_origin_record = copy.deepcopy(record)
        self.bound_root = root; self._seen_active = root
        self.selector_root = root if self.editing else None
        self._set_style(style); self._display(record)
        self._last_model_style = stable_json(style)
        self._live_due = None
        if self.editing: self._open_atom_selector_ready()

    def _build(self, record, style, document, replacement=None):
        if document != c4d.documents.GetActiveDocument(): raise ValueError("场景已切换，请重新应用")
        record = validate_record(record, require_3d=True)
        root = c4d_builder.build_model(document, record, style, replace_root=replacement)
        resource_key = self._resource_key(record)
        if self._usage_key != resource_key:
            try: self.usage.record_use(record)
            except Exception as exc: Backend._log(str(exc))
            self._usage_key = resource_key
        # Slider changes should not reload the 2D bitmap or reinitialise controls.
        self.bound_root = root; self._seen_active = root
        self.selector_root = root if self.editing else None
        self.current_record = copy.deepcopy(record)
        self.style = copy.deepcopy(style)
        self._last_model_style = stable_json(style)
        self._live_due = None
        self._status("实时预览 · 完成后保留当前模型")
        c4d.EventAdd()
        return root

    def _apply_flatten(self, atom_ids=None, plane="auto"):
        try:
            record = self._record(); style = self._get_style()
            style["position_overrides"] = flatten_overrides(record, style["position_overrides"], atom_ids, plane)
            style["plane_groups"] = {}
            self._set_style(style)
            if self.editor: self.editor.set_groups({})
            self._queue_live()
            self._status("已按二维展开 · 外围链段跟随")
            return True
        except Exception as exc: self._error(exc); return False

    def _restore_3d(self):
        style = self._get_style(); style["position_overrides"] = {}; style["plane_groups"] = {}
        self._set_style(style)
        if self.editor: self.editor.set_groups({})
        self._queue_live()
        return True

    def _apply_orientation(self, orientation, center_atom_ids):
        style = self._get_style()
        style["orientation"] = orientation
        style["center_atom_ids"] = list(center_atom_ids)
        self._set_style(style); self._queue_live()
        return copy.deepcopy(self.style)

    def _select_model_atoms(self, atom_ids):
        if self.selector_root is not None: return super()._select_model_atoms(atom_ids)

    def _apply_local_appearance(self, kind, keys, value):
        """Store display radii on the selected structure without changing its graph."""
        record = self._record()
        style = self._get_style()
        valid_atoms = {atom["id"] for atom in record["atoms"]}
        valid_bonds = {"%d:%d" % tuple(sorted((bond["a"], bond["b"])))
                       for bond in record["bonds"]}
        if kind == "atoms":
            if not set(keys) <= valid_atoms: raise ValueError("选择包含不存在的原子")
            for key in keys: style["atom_radius_overrides"][str(key)] = value
        elif kind == "bonds":
            if not set(keys) <= valid_bonds: raise ValueError("选择包含不存在的化学键")
            for key in keys: style["bond_radius_overrides"][key] = value
        elif kind == "reset":
            for key in keys["atoms"]: style["atom_radius_overrides"].pop(str(key), None)
            for key in keys["bonds"]: style["bond_radius_overrides"].pop(key, None)
        else:
            raise ValueError("局部外观操作无效")
        self._set_style(style)
        self._queue_live()
        return copy.deepcopy(self.style)

    def _apply_plane_groups(self, groups):
        try:
            record = validate_record(self._record(), require_3d=True); style = self._get_style()
            groups = normalized_plane_groups(groups)
            style["plane_groups"] = groups
            style["position_overrides"] = apply_plane_groups(record, groups)
            self._set_style(style)
            self.editor.set_groups(groups)
            self._queue_live()
            return True
        except Exception as exc: self._error(exc); return False

    def _save_configuration(self, save_as=False, name=None):
        record = self._record(); style = self._get_style()
        if self.editor and self.editor.groups_dirty:
            style["plane_groups"] = normalized_plane_groups(self.editor.groups)
            style["position_overrides"] = apply_plane_groups(record, style["plane_groups"])
        existing = {i["id"]: i for i in self.library.all()}
        configuration_id = self.configuration_id if self.configuration_id in existing else None
        previous = existing.get(configuration_id)
        category = (self.folder_current.removeprefix("folder:") if self.folder_current.startswith("folder:")
                    else previous["category"] if previous and not save_as else "未分类")
        entry = self.library.save_configuration(record, style, name or self.GetString(LABEL), category,
                                                None if save_as else configuration_id)
        self.configuration_id = entry["id"]
        self.current_record["configuration_id"] = entry["id"]
        self.current_record["name"] = entry["label"]
        self.current_record["list_source"] = "收藏"
        self.SetString(LABEL, entry["label"])
        remembered = copy.deepcopy(entry["record"])
        remembered["name"] = entry["label"]; remembered["list_source"] = "收藏"
        self.usage.remember(remembered)
        self._rebuild_folders()
        self._refresh_browser_records()
        if self.selected >= 0: self.selected_cards = {self.selected}
        self._cards(); self._queue_live()
        self._status("已保存配置："+entry["label"])

    def _delete_resources(self):
        chosen = [self.records[i] for i in sorted(self.selected_cards)
                  if 0 <= i < len(self.records)]
        if not chosen: return
        self.library.remove_many([self._resource_key(record) for record in chosen])
        self.usage.remove_records(chosen)
        if self.folder_current == "search":
            removed = {self._resource_key(record) for record in chosen}
            self.records = [record for record in self.records if self._resource_key(record) not in removed]
            self.selected_cards = set()
            self.selected = next((i for i,r in enumerate(self.records) if self.current_record and
                                  self._resource_key(r) == self._resource_key(self.current_record)), -1)
        else:
            self._refresh_browser_records(); self.selected_cards = set()
        self._cards(); self._status("已删除 %d 个资源" % len(chosen))

    @staticmethod
    def _has_theme(record):
        return record.get("depiction_version") == DEPICTION_VERSION and all(
                   record.get(key) and os.path.isfile(record[key]) for key in
                   ("transparent_thumbnail", "transparent_dark_thumbnail"))

    def _apply_current(self, commit_planes=True):
        if not self.session_active: return None
        if self._session_document != c4d.documents.GetActiveDocument():
            self._finish_session(flush=False)
            raise ValueError("场景已切换，实时联动已结束")
        record = self._record(); style = self._get_style()
        commit = bool(commit_planes and self.editor and self.editor.groups_dirty)
        if commit:
            style["plane_groups"] = normalized_plane_groups(self.editor.groups)
            style["position_overrides"] = apply_plane_groups(record, style["plane_groups"])
        record["name"] = self.GetString(LABEL).strip() or record["name"]
        replacement = self.bound_root if self._binding_valid() else None
        document = c4d.documents.GetActiveDocument()
        if record.get("coordinates_ready") and record.get("has_3d"):
            if (replacement is not None and self._last_model_style == stable_json(style)
                    and c4d_builder.read_model(replacement)[0] == record):
                return replacement
            root = self._build(record, style, document, replacement)
            if commit: self.editor.set_groups(style["plane_groups"])
            return root
        self._start({"action":"generate","record":record}, "generate", style=style,
                    replacement=replacement, commit_planes=commit)

    def _finish_session(self, flush=True):
        if (flush and self._live_due is not None and self._binding_valid() and
                self.current_record and self.current_record.get("coordinates_ready")):
            self._apply_current()
        self.session_active = False
        self.bound_root = None
        self.selector_root = None
        self._session_document = None
        self._live_due = None
        self._seen_active = self._managed_selection(c4d.documents.GetActiveDocument())
        self.Enable(FINISH, False)
        self._update_smart_controls()

    def _apply_color_preset(self, index):
        if not 1 <= index < len(COLOR_PRESETS):
            return
        label, spec = COLOR_PRESETS[index]
        style = self._get_style()
        elements = self.available_elements or ELEMENTS
        if index == 1:
            for element in elements:
                style["element_colors"].pop(element, None)
                style["bond_element_colors"].pop(element, None)
            style["bond_color"] = list(DEFAULT_STYLE["bond_color"])
        else:
            palette = spec["elements"]
            for element in elements:
                if element in palette:
                    style["element_colors"][element] = list(palette[element])
                    style["bond_element_colors"][element] = list(palette[element])
            style["bond_color"] = list(spec["bond_color"])
        self._set_style(style)
        self.SetInt32(COLOR_PRESET, index)
        self._queue_live()
        self._status("已切换配色：" + label)

    def _rebind_selected_model(self):
        document = c4d.documents.GetActiveDocument()
        root = self._managed_selection(document)
        if root is None:
            raise ValueError("请先在对象管理器中选中本工具生成的分子")
        if hasattr(c4d_builder, "_get_meta") and hasattr(c4d_builder, "_signature"):
            meta = c4d_builder._get_meta(root)
            if meta is None:
                raise ValueError("所选对象缺少 SciMol 元数据")
            signature_matches = meta.get("signature") == c4d_builder._signature(root)
            if not signature_matches and meta.get("signature_version", 1) == 1:
                signature_matches = (
                    meta.get("signature") == c4d_builder._signature(root, include_caps=False)
                    and all(obj[c4d.PRIM_CYLINDER_CAPS] for obj in c4d_builder._walk(root)
                            if obj.CheckType(c4d.Ocylinder))
                )
            if not signature_matches:
                record, style = c4d_builder.read_model(root)
                self.session_active = False
                self.bound_root = None
                self._session_document = None
                self.Enable(FINISH, False)
                self._set_style(style)
                self._display(record)
                raise ValueError("模型内部或材质已被手工修改，已读取参数到面板，未直接接管")
        self.backend.cancel()
        self._set_busy(False)
        self.session_active = True
        self._session_document = document
        self._bind_root(root)
        self.Enable(FINISH, True)
        self.SetInt32(COLOR_PRESET, 0)
        self._update_smart_controls()
        if self.current_record and (not self._has_theme(self.current_record) or
                                    not self._has_atom_preview(self.current_record)):
            self._start({"action": "preview", "record": self.current_record},
                        "theme", structure_key=self.current_record["structure_key"])
        self._status("已接管场景分子 · 可直接实时调整")

    def _drag_asset(self, index, msg, area):
        # Kept for older callers; thumbnails never initiate scene drag/drop.
        return False

    def _resource_menu(self, index):
        if index not in self.selected_cards:
            if self.session_active:
                self.selected_cards = {index}; self._cards()
            else:
                self._select(index, generate=False)
        menu = c4d.BaseContainer()
        if len(self.selected_cards) == 1:
            menu.InsData(1,"重命名")
            if self.current_record and self._resource_key(self.current_record) == self._resource_key(self.records[index]):
                menu.InsData(2,"另存为配置")
        menu.InsData(3,"删除所选（%d）" % len(self.selected_cards))
        choice = c4d.gui.ShowPopupDialog(self, menu, c4d.MOUSEPOS, c4d.MOUSEPOS)
        if choice == 1:
            record = copy.deepcopy(self.records[index])
            name = c4d.gui.InputDialog("结构名称", record["name"])
            if name:
                record["name"] = name[:300]
                key = self._resource_key(record)
                if key in {i["id"] for i in self.library.all()}:
                    self.library.rename_item(key, name)
                self.usage.remember(record)
                self.records[index]["name"] = name[:300]
                if self.current_record and self._resource_key(self.current_record) == key:
                    self._display(record); self._queue_live()
                self._cards()
        elif choice == 2: self.Command(SAVE, c4d.BaseContainer())
        elif choice == 3: self._delete_resources()

    def _suggest(self):
        raw = self.GetString(INPUT)
        cleaned = normalize_query_text(raw)
        if not self.search_pending:
            hint = smart_input_hint(raw)
            self.search_message = hint
            self.SetString(SEARCH_STATUS, hint)
        actions = []
        seen_labels = set()
        query = cleaned.casefold()
        if query:
            for item in self.library.all():
                label = str(item.get("label") or "").strip()
                if label and query in label.casefold() and label not in seen_labels:
                    seen_labels.add(label)
                    actions.append(("favorite", label, item))
            for name in suggest_names(cleaned, limit=6):
                if name not in seen_labels:
                    seen_labels.add(name)
                    actions.append(("query", name, name))
        self._suggestion_actions = actions[:4]
        self.suggestions = [label for _, label, _ in self._suggestion_actions]
        self.LayoutFlushGroup(SUGGEST_GROUP)
        for i, (kind, label, _) in enumerate(self._suggestion_actions):
            short = label if len(label) <= 10 else label[:9] + "…"
            tip = ("打开收藏预设：%s" if kind == "favorite" else "检索结构：%s") % label
            add_action(self, SUGGEST_BASE + i, short, tip)
        self.LayoutChanged(SUGGEST_GROUP)

    def _queue_live(self):
        # Throttle rather than debounce: sustained slider movement stays live.
        if self.session_active and self._live_due is None:
            self._live_due = time.monotonic() + .04

    def Timer(self, msg):
        now = time.monotonic()
        if (self.right_visible and self.editor and self.editor.IsOpen() and
                now >= self._follow_retry_due and not self._window_follower.is_running):
            # Recover after minimize/restore; docked windows are left to C4D.
            self._follow_retry_due = now + 1.
            self._window_follower.start(self, self.editor)
        if self.search_pending and now >= self._search_pulse_due:
            self._search_pulse_due = now + .35
            self._search_pulse = (self._search_pulse + 1) % 4
            self.search_message = "正在搜索" + "." * (self._search_pulse + 1)
            self.SetString(SEARCH_STATUS, self.search_message)
            if self.thumbnail_area: self.thumbnail_area.Redraw()
        ready = bool(self.current_record and self.current_record.get("coordinates_ready"))
        if self._live_due is not None and now >= self._live_due and ready:
            self._live_due = None
            try:
                if self._binding_valid(): self._apply_current()
            except Exception as exc: self._error(exc)
        if now >= self._poll_due and not self.busy and self._live_due is None:
            self._poll_due = now+.5
            document = c4d.documents.GetActiveDocument()
            if self.session_active and self._session_document != document:
                self._finish_session(flush=False)
                self._status("场景已切换，实时联动已结束")
            elif not self.session_active:
                active = self._managed_selection(document)
                self.Enable(REBIND_ACTIVE, active is not None)
                if active != self._seen_active:
                    self._seen_active = active
                    if active is not None and not self.status_text.startswith("已完成"):
                        self._status("已选中场景分子 · 可点击「接管所选」继续调整")
        for backend, background in ((self.backend, False), (self.preview_backend, True)):
            for _ in range(8):
                try: token, context, result, elapsed = backend.results.get_nowait()
                except queue.Empty: break
                if not self.alive or token != backend.generation: continue
                if background: self._preview_pending = False
                else: self._set_busy(False)
                self._accept_result(context, result)

    def _accept_result(self, context, result):
        if context["document"] != c4d.documents.GetActiveDocument():
            if context.get("operation") == "resolve": self._end_search("场景已切换，搜索已取消")
            self._status("场景已切换，本次结果已丢弃"); return
        try:
            if not result.get("ok"): raise ValueError(result.get("error", "处理失败"))
            operation = context["operation"]
            if operation == "common":
                self.builtins = copy.deepcopy(result.get("records",[])); self._refresh_lists()
            elif operation == "resolve":
                records = result.get("records", [])
                self._cache_search(context.get("query"), records)
                self._end_search("找到 %d 个结构" % len(records) if records else "未找到匹配结构")
                self._show_records(records, "resolve")
            elif operation == "generate":
                if not self.session_active: return
                replacement = context.get("replacement")
                if replacement is not None and replacement != self.bound_root:
                    raise ValueError("所选模型已切换，本次更新已取消")
                self.current_record = validate_record(result["record"])
                self._apply_current()
                if context.get("commit_planes"):
                    self.editor.set_groups(context["style"]["plane_groups"])
            elif operation == "themes":
                self._remember_previews(result.get("records", []))
                self._cards()
                self._status("%d 个结构" % len(self.records))
                self._refresh_missing_previews()
            elif operation in ("asset", "preview", "theme"):
                if not self.current_record or self.current_record["structure_key"] != context["structure_key"]: return
                if operation == "asset":
                    if record_integrity(self.current_record) != context["source_key"]: return
                elif record_integrity(self.current_record) != context["source_integrity"]: return
                if (operation != "asset" and
                        context.get("resource_key", self._resource_key(self.current_record)) != self._resource_key(self.current_record)): return
                record = validate_record(result["record"])
                if operation != "asset" and record_integrity(record) != context["source_integrity"]: return
                if operation == "asset":
                    if not self.session_active: return
                    self._ready_records[context["source_key"]] = copy.deepcopy(record)
                    if len(self._ready_records) > 100:
                        self._ready_records.pop(next(iter(self._ready_records)))
                # The result must not replace a rename/configuration made in flight.
                record["name"] = self.current_record["name"]
                for field in ("configuration_id", "list_source"):
                    if field in self.current_record: record[field] = self.current_record[field]
                    else: record.pop(field, None)
                if operation != "asset":
                    # A 2D-only preview cannot roll back newly generated 3D data.
                    current = copy.deepcopy(self.current_record)
                    self._copy_preview(current, record)
                    record = current
                for i, listed in enumerate(self.records):
                    if self._resource_key(listed) == self._resource_key(record):
                        self.records[i] = copy.deepcopy(record)
                self._display(record); self._cards()
                self._remember_previews([record])
                if operation == "asset": self._apply_current()
                if self.selector_pending: self._open_atom_selector_ready()
        except Exception as exc:
            if context.get("operation") == "resolve": self._end_search(str(exc))
            self._error(exc)

    def Message(self, msg, result):
        if (msg.GetId() == getattr(c4d, "BFM_INPUT", -1) and
                msg.GetInt32(getattr(c4d, "BFM_INPUT_DEVICE", -1)) == getattr(c4d, "BFM_INPUT_KEYBOARD", -2) and
                msg.GetInt32(getattr(c4d, "BFM_INPUT_VALUE", -1)) and
                hasattr(self, "IsActive") and self.IsActive(INPUT)):
            channel = msg.GetInt32(getattr(c4d, "BFM_INPUT_CHANNEL", -1))
            asc = msg.GetString(getattr(c4d, "BFM_INPUT_ASC", -1)) if hasattr(msg, "GetString") else ""
            if channel == getattr(c4d, "KEY_ENTER", 61709) or asc in ("\r", "\n"):
                self.Command(RESOLVE, c4d.BaseContainer())
                return True
        if msg.GetId() == c4d.BFM_WEIGHTS_CHANGED and msg.GetInt32(c4d.BFM_WEIGHTS_CHANGED) == ROOT_LAYOUT:
            self._remember_pane_weights()
        help_map = {INPUT:"输入或粘贴名称、分子式、SMILES；自动识别（回车直达）。",
                    PASTE_SEARCH:"读取剪贴板中的名称、分子式或 SMILES 并立即搜索。",
                    STICK_MODE:"切换为细棍骨架模式；保持球棍参数备忘。",
                    COLOR_PRESET:"一键套用科研期刊配色主题（Classic CPK / Nature / Science / 白底插图）。",
                    REBIND_ACTIVE:"重新绑定对象管理器中选中的 SciMol 分子，继续实时调整。",
                    SMILES_INPUT:"粘贴 ChemDraw 的 SMILES，然后点击右侧确认。",
                    LABEL:"重命名当前结构。已绑定的模型会自动更新。",
                    BOND_MATERIAL:"勾选统一键色；未勾选时分别设置元素的键色。",
                    ELEMENT_COLOR:"所选元素的球色，修改后自动应用。",
                    SIZE_ELEMENT:"只列出当前结构的元素；选择要缩放的元素，不影响颜色选择。",
                    ELEMENT_SIZE:"元素缩放倍率：1 为原大小，0.5 为一半，2 为两倍；支持一位小数。",
                    ELEMENT_SIZE_SLIDER:"元素缩放 0.1–3 倍；数字框可超出范围，分段和键粗细不变。",
                    BOND_COLOR:"独立的键色，修改后自动应用。",
                    SPHERE_SEGMENTS:"球母体分段；输入范围 3–512。",
                    CYLINDER_SEGMENTS:"棍母体圆周分段；输入范围 3–512。",
                    MATERIAL_INHERIT:"继承场景共享材质，改色会同步到同材质模型；取消后使用独立材质。",
                    STATUS:self.status_text, WARNING:self.warning_text}
        if hover_help(self,msg,result,help_map): return True
        return c4d.gui.GeDialog.Message(self,msg,result)

    def Command(self, identifier, msg):
        try:
            if identifier in RESET_SLIDERS:
                slider = RESET_SLIDERS[identifier]
                style = self._get_style()
                if slider == ELEMENT_SIZE_SLIDER:
                    element = self._size_element()
                    if element is None: return True
                    style["element_scales"].pop(element, None)
                else:
                    key = next(key for _, item, key, _, _ in PAIRS if item == slider)
                    style[key] = DEFAULT_STYLE[key]
                    if key == "atom_radius" and style["representation"] == "ball_stick":
                        style["ball_stick_radius"] = DEFAULT_STYLE["atom_radius"]
                self._set_style(style); self._queue_live()
            elif identifier == RIGHT_TOGGLE:
                if self.editor and self.editor.IsOpen(): self._close_atom_selector()
                else: self._open_atom_selector()
            elif identifier == LEFT_TOGGLE:
                # Compatibility only; the resource browser is now permanent.
                return True
            elif identifier == INPUT: self._suggest()
            elif SUGGEST_BASE <= identifier < SUGGEST_BASE+4:
                index = identifier - SUGGEST_BASE
                if index < len(self._suggestion_actions):
                    kind, label, payload = self._suggestion_actions[index]
                    if kind == "favorite":
                        target_folder = "favorites"
                        if payload.get("category") and payload["category"] != "未分类":
                            target_folder = "folder:" + payload["category"]
                        self._browse_folder(target_folder)
                        match = next((i for i, r in enumerate(self.records)
                                      if self._resource_key(r) == payload["id"] or
                                      r["structure_key"] == payload["record"]["structure_key"]), None)
                        if match is not None:
                            self._select(match)
                    else:
                        self.SetString(INPUT, label)
                        self.Command(RESOLVE, msg)
                elif index < len(self.suggestions):
                    self.SetString(INPUT, self.suggestions[index])
                    self.Command(RESOLVE, msg)
            elif identifier == PASTE_SEARCH:
                value = c4d.GetStringFromClipboard()
                cleaned = normalize_query_text(value)
                if not cleaned: raise ValueError("剪贴板没有可识别的分子名称、分子式或 SMILES")
                self.SetString(INPUT, cleaned)
                self._suggest()
                self._search(cleaned)
            elif identifier == PASTE:
                value = c4d.GetStringFromClipboard()
                if not value: raise ValueError("剪贴板没有 SMILES 文本")
                self.SetString(INPUT,value.strip())
            elif identifier in (RESOLVE, CONFIRM):
                text = normalize_query_text(self.GetString(INPUT))
                if not text: raise ValueError("请输入名称或粘贴 SMILES")
                self._search(text)
            elif identifier == EDIT_MODE:
                if self.editing: self._set_editor_visible(False)
                else: self._open_atom_selector()
            elif identifier == FINISH:
                self._finish_session()
                if not self.search_pending:
                    self.backend.cancel(); self._set_busy(False)
                self._status("已完成 · 当前模型已解除联动")
            elif identifier == CANCEL:
                self.backend.cancel(); self._set_busy(False)
                if self.search_pending: self._end_search("搜索已取消")
            elif identifier == GENERATE: self._apply_current()
            elif identifier == READ_MODEL:
                self._status("读取已取消；完成后的模型不再联动")
            elif identifier == REBIND_ACTIVE:
                self._rebind_selected_model()
            elif identifier in (CONFIG_SAVE, CONFIG_SAVE_AS, SAVE):
                save_as = identifier in (CONFIG_SAVE_AS, SAVE)
                name = None
                if save_as:
                    name = c4d.gui.InputDialog("另存为配置", self.GetString(LABEL))
                    if name is None: return True
                    if not name.strip(): raise ValueError("配置名称不能为空")
                self._save_configuration(save_as, name)
            elif identifier == DELETE_SELECTED: self._delete_resources()
            elif identifier == RESET:
                style = copy.deepcopy(DEFAULT_STYLE); style["representation"] = "continuous"
                self._set_style(style)
                self.SetInt32(COLOR_PRESET, 0)
                if self.editor: self.editor.set_groups({})
                self._queue_live()
            elif identifier == COLOR_PRESET:
                self._apply_color_preset(self.GetInt32(COLOR_PRESET))
            elif identifier == STICK_MODE:
                style = self._get_style()
                if style["representation"] == "ball_stick":
                    style["ball_stick_radius"] = style["atom_radius"]
                style["representation"] = "continuous"
                style["atom_radius"] = 0.12
                style["bond_radius"] = 0.10
                self._set_style(style)
                self._queue_live()
                self._status("已切换细棍骨架模式")
            elif identifier in (ELEMENT, BOND_ELEMENT):
                self._element_color() if identifier == ELEMENT else self._bond_color()
            elif identifier == SIZE_ELEMENT:
                self._element_size()
            elif identifier in (ELEMENT_SIZE, ELEMENT_SIZE_SLIDER):
                element = self._size_element()
                if element is None: return True
                style = self._get_style()
                factor = round(self.GetFloat(identifier), 1)
                if identifier == ELEMENT_SIZE_SLIDER: factor = min(3., max(.1, factor))
                style["element_scales"][element] = factor
                self._set_style(style)
                self._queue_live()
            elif identifier in (BALL_STICK, SPACE_FILL):
                style = self._get_style()
                fill = identifier == SPACE_FILL
                if fill and style["representation"] == "ball_stick": style["ball_stick_radius"] = style["atom_radius"]
                style["representation"] = "space_fill" if fill else "ball_stick"
                style["atom_radius"] = 1. if fill else style["ball_stick_radius"]
                self._set_style(style); self._queue_live()
            elif identifier in LIVE_CONTROLS or any(identifier == s for _,s,_,_,_ in PAIRS):
                for number, slider, key, low, high in PAIRS:
                    if identifier == slider:
                        value = self.GetInt32(slider) if "segments" in key else self.GetFloat(slider)
                        if "segments" in key: self.SetInt32(number,value)
                        else: self._set_size_pair(number, slider, value, low, high)
                    elif identifier == number:
                        value = self.GetInt32(number) if "segments" in key else self.GetFloat(number)
                        if "segments" in key: self.SetInt32(slider,min(high,max(low,value)),min=low,max=high)
                        else: self._set_size_pair(number, slider, value, low, high)
                    if identifier in (number, slider) and key == "atom_radius":
                        self.style["representation"] = "continuous"
                if identifier == ELEMENT_COLOR:
                    v=self.GetColorField(ELEMENT_COLOR)["color"]
                    element = self._chosen_element(ELEMENT)
                    if element is not None: self.style["element_colors"][element]=[v.x,v.y,v.z]
                    self.SetInt32(COLOR_PRESET, 0)
                elif identifier == BOND_COLOR:
                    v=self.GetColorField(BOND_COLOR)["color"]; color=[v.x,v.y,v.z]
                    if self.GetBool(BOND_MATERIAL): self.style["bond_color"]=color
                    else:
                        element = self._chosen_element(BOND_ELEMENT)
                        if element is not None: self.style["bond_element_colors"][element]=color
                    self.SetInt32(COLOR_PRESET, 0)
                if identifier == BOND_MATERIAL:
                    self.style["bond_material"]="uniform" if self.GetBool(BOND_MATERIAL) else "element"; self._bond_color()
                if identifier == MATERIAL_INHERIT and self.GetBool(MATERIAL_INHERIT):
                    if self.current_record and hasattr(c4d_builder, "inherited_style"):
                        self._set_style(c4d_builder.inherited_style(
                            c4d.documents.GetActiveDocument(), self._record(), self._get_style()))
                if identifier == LABEL and self.current_record is not None:
                    name=self.GetString(LABEL).strip()
                    if name:
                        self.current_record["name"]=name[:300]
                        if 0 <= self.selected < len(self.records): self.records[self.selected]["name"]=name[:300]
                        self._cards()
                self._queue_live()
                if identifier in (ATOM_RADIUS, ATOM_SLIDER): self._element_size()
                if self.editor: self.editor.set_appearance(self._get_style())
            elif identifier == NEW_FOLDER:
                name = c4d.gui.InputDialog("新建文件夹", "新文件夹")
                if name:
                    self.library.create_folder(name); self._rebuild_folders(); self._browse_folder("folder:"+name.strip())
            elif identifier == MORE:
                menu=c4d.BaseContainer(); menu.InsData(1,"重命名文件夹"); menu.InsData(2,"导入收藏"); menu.InsData(3,"导出收藏")
                choice=c4d.gui.ShowPopupDialog(self,menu,c4d.MOUSEPOS,c4d.MOUSEPOS)
                if choice==1 and self.folder_current.startswith("folder:"):
                    old=self.folder_current.removeprefix("folder:"); name=c4d.gui.InputDialog("文件夹名称",old)
                    if name:
                        self.library.rename_folder(old,name); self.folder_current="folder:"+name.strip(); self._refresh_lists()
                elif choice in (2,3): return super().Command(IMPORT_LIBRARY if choice==2 else EXPORT,msg)
            else: return super().Command(identifier,msg)
        except Exception as exc: self._error(exc)
        return True

    def _on_brand_click(self):
        lines = [
            "分子球棍生成器 · SciMol C4D (v1.2.0)",
            "出品：与可 | YUKE (DeepLeap)",
            "先理解研究，再呈现视觉",
            "GitHub: https://github.com/DeepLeap/scimol-c4d",
        ]
        if self.current_record is not None:
            record = self._record()
            lines.extend([
                "",
                "当前结构：" + str(record.get("name", "")),
                "分子式：" + str(record.get("formula", "")),
                "SMILES：" + str(record.get("smiles", "")),
            ])
            warnings = record.get("warnings") or []
            if warnings:
                lines.append("\n".join(warnings))
        c4d.gui.MessageDialog("\n".join(lines))

    def DestroyWindow(self):
        getattr(self.preview_backend, "close", self.preview_backend.cancel)()
        return super().DestroyWindow()
