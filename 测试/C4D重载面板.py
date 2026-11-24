"""Developer reload that retains the user's selection, style and plane draft."""
import builtins
import copy
import importlib
from pathlib import Path
import sys

import c4d

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def refresh_flattened_hydrogens(panel):
    """Upgrade a live, wholly planar old preview without moving its skeleton.

    This is an explicit developer action after native acceptance, not automatic
    migration of saved configurations or independently edited scene objects.
    """
    import json
    from scimol_c4d import c4d_builder as builder, display_geometry as geometry
    from scimol_c4d.hydrogen_layout import arrange_hydrogens, collision_score
    from scimol_c4d.records import record_integrity

    document = c4d.documents.GetActiveDocument()
    assert panel._binding_valid() and not panel.editor.groups_dirty
    record = panel._record()
    integrity = record_integrity(record)
    style = panel._get_style()
    assert not style['plane_groups']
    root = panel.bound_root
    metadata = builder._get_meta(root)
    assert metadata and metadata['signature'] == builder._signature(root), '模型已被独立编辑'
    _, source, heavy = geometry._record_positions(record)
    positions = {int(key): value[:] for key, value in style['position_overrides'].items()}
    assert set(positions) == set(source), '需要完整拍平坐标'
    origin, normal = geometry._plane([positions[i] for i in sorted(heavy)])
    assert max(abs(geometry._dot(geometry._sub(positions[i], origin), normal))
               for i in heavy) < 1e-6, '当前骨架没有全部共面'
    adjusted = arrange_hydrogens(record, source, positions, heavy, normal)
    elements = {atom['id']: atom['element'] for atom in record['atoms']}
    old_score = collision_score(positions, elements, record['bonds'])
    new_score = collision_score(adjusted, elements, record['bonds'])
    # The preview may already have received the early unconstrained clearance
    # fix. Preserving handedness and a natural OH angle takes priority over a
    # still lower soft score from an incorrect-side hydrogen.
    assert all(adjusted[i] == positions[i] for i in heavy)
    before_objects = document.GetObjects()
    before_materials = document.GetMaterials()
    active_object = document.GetActiveObject()
    nodes = {obj.GetName(): obj for obj in builder._walk(root)}
    heavy_positions = {i: nodes['原子_%s_%s' % (elements[i], i)].GetRelPos() for i in heavy}
    updated = copy.deepcopy(style)
    updated['position_overrides'] = {str(key): value for key, value in adjusted.items()}
    expected = builder._geometry_positions(record, updated)
    assert max((expected[i]-heavy_positions[i]).GetLength() for i in heavy) < 1e-5
    panel._set_style(updated)
    try:
        assert panel._apply_current(commit_planes=False) == root
    except Exception:
        panel._set_style(style)
        raise
    assert document.GetObjects() == before_objects
    assert document.GetMaterials() == before_materials
    assert {obj.GetName(): obj for obj in builder._walk(root)} == nodes
    assert max((nodes['原子_%s_%s' % (elements[i], i)].GetRelPos()-heavy_positions[i]).GetLength()
               for i in heavy) < 1e-5
    assert record_integrity(panel.current_record) == integrity
    if active_object and active_object.IsAlive():
        document.SetActiveObject(active_object)
    panel._status('拍平氢方向已刷新 · 骨架保持')
    c4d.EventAdd()
    report = {'status': 'PASS', 'record': record['name'],
              'before_score': old_score, 'after_score': new_score,
              'heavy_positions_unchanged': True, 'object_identity_preserved': True,
              'material_identity_preserved': True, 'original_record_unchanged': True,
              'document_roots': len(document.GetObjects())}
    (ROOT / '测试/输出/拍平氢当前预览刷新.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return report


def run():
    previous = getattr(builtins, '_scimol_native_dialog_v1', None)
    state = None
    width, height = 1120, 720
    if previous and previous.IsOpen():
        from scimol_c4d import browser_ui as old_ui
        previous._remember_pane_weights()
        dim = previous.GetItemDim(old_ui.ROOT_LAYOUT)
        width, height = max(800, dim['w']), max(640, dim['h'] + 100)
        state = {key: copy.deepcopy(getattr(previous, key)) for key in (
            'records', 'builtins', 'favorite_items', 'current_record', 'folder_current',
            'selected', 'view', 'configuration_id', 'preset_origin_record',
            'pane_weights', 'right_visible', 'editing')}
        state['selected_cards'] = set(getattr(previous, 'selected_cards', {previous.selected}) or ())
        state['style'] = previous._get_style()
        state['bound_root'] = previous.bound_root
        state['session_active'] = getattr(previous, 'session_active', previous.bound_root is not None)
        state['session_document'] = getattr(previous, '_session_document',
                                          c4d.documents.GetActiveDocument() if state['session_active'] else None)
        state['selector_drafts'] = previous.selector_drafts
        state['groups'] = copy.deepcopy(previous.editor.groups)
        state['dirty'] = previous.editor.groups_dirty
        state['selected_ids'] = set(previous.editor.selected_ids)
        state['selected_bonds'] = set(getattr(previous.editor, 'selected_bonds', set()))
        state['background_white'] = getattr(previous.editor, 'background_white', 0)
        state['inputs'] = (previous.GetString(old_ui.INPUT), previous.GetString(old_ui.SMILES_INPUT))
        state['ready_records'] = copy.deepcopy(getattr(previous, '_ready_records', {}))
        state['resolve_cache'] = copy.deepcopy(getattr(previous, '_resolve_cache', {}))
        state['usage_key'] = getattr(previous, '_usage_key', None)
        state['search_records'] = copy.deepcopy(getattr(previous, 'search_records',
                                    previous.records if previous.folder_current == 'search' else []))
        old_elements = getattr(previous, 'available_elements', old_ui.ELEMENTS)
        state['element_choices'] = {}
        for identifier in (old_ui.ELEMENT, old_ui.BOND_ELEMENT, old_ui.SIZE_ELEMENT):
            choices = (getattr(previous, 'size_elements', old_elements)
                       if identifier == old_ui.SIZE_ELEMENT else old_elements)
            index = previous.GetInt32(identifier)
            if 0 <= index < len(choices):
                state['element_choices'][identifier] = choices[index]
        if getattr(previous, '_window_follower', None): previous._window_follower.stop()
        getattr(previous.backend, 'close', previous.backend.cancel)()
        if getattr(previous, 'preview_backend', None):
            getattr(previous.preview_backend, 'close', previous.preview_backend.cancel)()
        previous.Close()
    for name in ('records', 'search_index', 'resolve_cache', 'backend', 'hydrogen_layout', 'display_geometry', 'appearance_scale', 'library', 'usage', 'c4d_builder', 'native_ui', 'atom_selector', 'resource_browser',
                 'floating_windows', 'browser_layout', 'ui', 'browser_ui'):
        module = importlib.import_module('scimol_c4d.' + name)
        importlib.reload(module)
    from scimol_c4d import browser_ui as ui, atom_selector
    panel = ui.BrowserDialog()
    builtins._scimol_native_dialog_v1 = panel
    assert panel.Open(c4d.DLG_TYPE_ASYNC, defaultw=width, defaulth=height)
    if state:
        panel.backend.cancel(); panel._set_busy(False)
        for key in ('records', 'builtins', 'favorite_items', 'current_record', 'folder_current',
                    'selected', 'view', 'configuration_id', 'preset_origin_record',
                    'pane_weights', 'right_visible', 'editing', 'bound_root', 'selector_drafts'):
            setattr(panel, key, state[key])
        panel.selected_cards = state['selected_cards']
        panel.session_active = state['session_active']
        panel._session_document = state['session_document']
        panel.Enable(ui.FINISH, panel.session_active)
        panel._set_style(state['style'])
        panel.SetString(ui.INPUT, state['inputs'][0] or state['inputs'][1])
        panel._ready_records = state['ready_records']
        panel._resolve_cache = state['resolve_cache']
        panel._usage_key = state['usage_key']
        panel.search_records = state['search_records']
        panel._seen_active = panel._managed_selection(c4d.documents.GetActiveDocument())
        panel.editor.background_white = state['background_white']
        for identifier in (atom_selector.BACKGROUND_WHITE, atom_selector.BACKGROUND_SLIDER):
            panel.editor.SetInt32(identifier, state['background_white'], min=0, max=100)
        if panel.current_record:
            panel._display(panel.current_record)
            for identifier, symbol in state['element_choices'].items():
                if symbol in panel.available_elements:
                    panel.SetInt32(identifier, panel.available_elements.index(symbol))
            panel._element_color(); panel._bond_color(); panel._element_size()
            panel.editor.set_groups(state['groups'])
            panel.editor.groups_dirty = state['dirty']
            panel.editor.selected_ids = state['selected_ids']
            panel.editor.selected_bonds = state['selected_bonds']
            panel.editor.set_appearance(panel.style)
            panel.selector_root = panel.bound_root
        if panel.right_visible and panel.current_record: panel._open_atom_selector_ready()
        else: panel._set_editor_visible(False)
        panel._set_pane_weights(); panel.LayoutChanged(ui.ROOT_LAYOUT)
        panel._rebuild_folders(); panel._cards()
        if panel.folder_current != 'search': panel._refresh_browser_records()
        if panel.current_record and not panel._has_theme(panel.current_record):
            panel._start({'action': 'preview', 'record': panel.current_record}, 'theme',
                         structure_key=panel.current_record['structure_key'])
        else:
            missing = [r for r in panel.records if not panel._has_theme(r)][:24]
            if missing: panel._start({'action': 'previews', 'records': missing}, 'themes', view=panel.view)
    print('新版原生面板已打开；当前结构、调整参数和分组草稿保留。')
    return panel
