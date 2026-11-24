"""Native callback checks on our disposable comparison document only."""

import builtins
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

import c4d

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run():
    from scimol_c4d import atom_selector, c4d_builder, ui
    from scimol_c4d.library import Library
    demo = builtins._scimol_flatten_demo
    document, root = demo['doc'], demo['flat']
    assert document.IsAlive() and c4d.documents.GetActiveDocument() == document
    assert document.GetDocumentName().startswith(('重原子拍平对比_', '平面分组与填充_'))
    panel = builtins._scimol_native_dialog_v1
    selector = panel.atom_selector
    assert panel.IsOpen() and selector and selector.IsOpen()
    checks = {}
    assert panel._restore_3d()
    panel.Command(ui.BALL_STICK, c4d.BaseContainer())
    record, original_style = c4d_builder.read_model(root)
    original_record = copy.deepcopy(record)
    originals = {a['id']: [a[k] for k in ('x', 'y', 'z')] for a in record['atoms']}
    original_matrix = root.GetMl()
    material_count = len(document.GetMaterials())
    original_materials = c4d_builder._prototype_materials(root)

    # Native user area uses the actual drawn image dimensions, not guessed pixels.
    left, top, width, height = selector._image._image_box()
    source_w, source_h = selector._image.source_size
    px, py = selector._image.positions[7]
    x, y = left + px * width / source_w, top + py * height / source_h
    selector.Command(atom_selector.CLEAR, c4d.BaseContainer())
    selector._select_box(x, y, x, y)
    assert selector.selected_ids == {7}
    assert document.GetActiveObject().GetName() == '原子_O_7'
    checks['diagram_click_selects_c4d_O_7'] = True
    selector.Command(atom_selector.CLEAR, c4d.BaseContainer())
    selector._select_box(left, top, left + width, top + height)
    assert selector.selected_ids == set(range(8))
    checks['diagram_rectangle_selects_all_heavy_atoms'] = True

    # Exercise the same helpers used by the human right-click menu; do not open
    # the blocking popup from MCP. Assignments must not move the model yet.
    selector.selected_ids = set(range(6))
    selector._assign_group()
    selector.selected_ids = {7}
    selector._assign_group()
    assert set(selector.groups) == {'1', '2'}
    selector._assign_group('1')
    assert set(selector.groups) == {'1'}
    selector.selected_ids = {6}
    selector._assign_group()
    pending = copy.deepcopy(selector.groups)
    assert pending['1']['atom_ids'] == [0, 1, 2, 3, 4, 5, 7]
    assert pending['2']['atom_ids'] == [6]
    assert c4d_builder.read_model(root)[1] == original_style
    checks['group_edits_staged_until_update'] = True
    selector.Command(atom_selector.APPLY_GROUPS, c4d.BaseContainer())
    record, style = c4d_builder.read_model(root)
    assert set(style['plane_groups']) == {'1', '2'}
    assert record == original_record
    assert root.GetMl() == original_matrix
    display = {i: style['position_overrides'].get(str(i), xyz) for i, xyz in originals.items()}
    group = style['plane_groups']['1']
    for atom_id in group['atom_ids']:
        error = sum((display[atom_id][k] - group['origin'][k]) * group['normal'][k] for k in range(3))
        assert abs(error) < 1e-8
    for bond in record['bonds']:
        a, b = bond['a'], bond['b']
        if record['atoms'][a]['element'] == 'H': a, b = b, a
        if record['atoms'][b]['element'] == 'H':
            for k in range(3):
                assert abs((display[b][k] - display[a][k]) - (originals[b][k] - originals[a][k])) < 1e-8
    checks['heavy_group_coplanar_H_direction_preserved_original_immutable'] = True
    assert len(document.GetMaterials()) == material_count
    assert c4d_builder._prototype_materials(root) == original_materials
    checks['plane_update_reuses_separate_atom_bond_materials'] = True

    # The two public buttons must preserve the coordinate layout and materials.
    ball_radius = style['atom_radius']
    carbon_before = next(o for o in c4d_builder._walk(root) if o.GetName() == '球母体_C')[c4d.PRIM_SPHERE_RAD]
    panel.Command(ui.SPACE_FILL, c4d.BaseContainer())
    _record, filled = c4d_builder.read_model(root)
    assert filled['representation'] == 'space_fill'
    assert filled['ball_stick_radius'] == ball_radius
    assert filled['position_overrides'] == style['position_overrides']
    assert filled['plane_groups'] == style['plane_groups']
    carbon_after = next(o for o in c4d_builder._walk(root) if o.GetName() == '球母体_C')[c4d.PRIM_SPHERE_RAD]
    bonds = next(o for o in c4d_builder._walk(root) if o.GetName() == '化学键')
    assert carbon_after > carbon_before * 4
    assert bonds[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] == c4d.MODE_OFF
    assert bonds[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] == c4d.MODE_OFF
    assert len(document.GetMaterials()) == material_count
    assert c4d_builder._prototype_materials(root) == original_materials
    checks['fill_enlarges_spheres_hides_bonds_preserves_layout_materials'] = True
    panel.Command(ui.BALL_STICK, c4d.BaseContainer())
    _record, returned = c4d_builder.read_model(root)
    assert returned['representation'] == 'ball_stick' and returned['atom_radius'] == ball_radius
    assert returned['plane_groups'] == style['plane_groups']
    assert returned['position_overrides'] == style['position_overrides']
    checks['ball_stick_button_restores_radius_and_groups'] = True
    assert document.DoUndo()
    assert c4d_builder.read_model(root)[1]['representation'] == 'space_fill'
    assert document.DoRedo()
    assert c4d_builder.read_model(root)[1]['representation'] == 'ball_stick'
    # A further update checks the regenerated signature after redo.
    c4d_builder.build_model(document, record, returned, replace_root=root)
    checks['single_step_undo_redo_followup_update'] = True

    temporary_library = Library(ROOT / '测试/输出' / ('平面库验收_' + uuid.uuid4().hex[:8]))
    temporary_library.save(record, filled, '平面填充验收', '验收')
    assert temporary_library.all()[0]['style'] == filled
    checks['favorite_preserves_planes_display_coordinates_and_representation'] = True

    # Leave a visible original-ball-stick / plane-adjusted-fill comparison.
    panel.Command(ui.SPACE_FILL, c4d.BaseContainer())
    root.SetName('右 · 平面分组后填充模型 · 氢保留方向')
    save_path = ROOT / '测试/输出' / ('平面分组与填充_' + uuid.uuid4().hex[:8] + '.c4d')
    assert c4d.documents.SaveDocument(document, str(save_path), c4d.SAVEDOCUMENTFLAGS_0, c4d.FORMAT_C4DEXPORT)
    document.SetDocumentPath(str(save_path.parent))
    document.SetDocumentName(save_path.name)
    committed = c4d_builder.read_model(root)[1]
    loaded = c4d.documents.LoadDocument(str(save_path), c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)
    assert loaded is not None
    try:
        loaded_root = next(o for o in loaded.GetObjects() if c4d_builder.is_managed(o) and c4d_builder.read_model(o)[1]['representation'] == 'space_fill')
        loaded_record, loaded_style = c4d_builder.read_model(loaded_root)
        assert loaded_style == committed
        c4d_builder.build_model(loaded, loaded_record, loaded_style, replace_root=loaded_root)
        checks['scene_save_load_and_safe_update'] = True
    finally:
        c4d.documents.KillDocument(loaded)
    selector._image.Redraw()
    c4d.EventAdd()
    report = {'status':'PASS', 'finished_at_utc':datetime.now(timezone.utc).isoformat(),
              'c4d_version':c4d.GetC4DVersion(), 'checks':checks, 'document':str(save_path),
              'native_windows_open':{'main':panel.IsOpen(), 'diagram':selector.IsOpen()},
              'physical_mouse_drag_and_popup_tested':False, 'render_started':False}
    (ROOT / '测试/输出/平面填充宿主验证.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    builtins._scimol_planes_fill_report = report
    builtins._scimol_flatten_demo['path'] = str(save_path)
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == '__main__':
    run()
