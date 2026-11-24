"""Real C4D callbacks in a disposable document; never render or edit user scenes."""
import builtins
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import tempfile
import traceback
import uuid

import c4d

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run():
    from scimol_c4d import browser_ui as ui, c4d_builder as builder, display_geometry
    from scimol_c4d.library import Library
    from scimol_c4d.records import normalized_style
    from scimol_c4d.usage import UsageStore
    panel = builtins._scimol_native_dialog_v1
    original_doc = c4d.documents.GetActiveDocument()
    # C4D can discard its pristine startup document when another one is
    # inserted. Keep a clone so that this empty starting state can be restored.
    startup_backup = original_doc.GetClone(c4d.COPYFLAGS_0)
    baseline = ([obj for obj in original_doc.GetObjects()], original_doc.GetMaterials(),
                original_doc.GetDocumentName(), original_doc.GetDocumentPath())
    snapshot = {key: getattr(panel, key) for key in (
        'library', 'usage', 'records', 'builtins', 'favorite_items', 'view', 'selected',
        'current_record', 'style', 'bound_root', '_seen_active', '_live_due', 'folder_current',
        'configuration_id', 'preset_origin_record', 'selector_root', 'selector_drafts',
        'right_visible', 'editing', 'pane_weights')}
    editor_state = (copy.deepcopy(panel.editor.groups), panel.editor.groups_dirty,
                    set(panel.editor.selected_ids))
    record = json.loads((ROOT / '测试/输出/苄醇三维.json').read_text(encoding='utf-8'))
    before_record = copy.deepcopy(record)
    token = uuid.uuid4().hex[:8]
    document = c4d.documents.BaseDocument()
    document.SetDocumentName('资源库隔离验收_' + token)
    c4d.documents.InsertBaseDocument(document)
    c4d.documents.SetActiveDocument(document)
    report = {'status': 'FAIL', 'c4d_version': c4d.GetC4DVersion(), 'checks': {},
              'physical_mouse_tested': False, 'render_started': False}
    checks = report['checks']
    loaded = None
    with tempfile.TemporaryDirectory(prefix='scimol-host-') as temporary:
        try:
            panel.backend.cancel(); panel._set_busy(False)
            panel.library = Library(Path(temporary) / 'library')
            panel.usage = UsageStore(Path(temporary) / 'usage')
            panel.selector_drafts = []; panel.bound_root = None
            panel.current_record = None; panel.editor.groups_dirty = False
            style = normalized_style()
            first = builder.build_model(document, record, style)
            material_count = len(document.GetMaterials())
            first_materials = builder._prototype_materials(first)
            second = builder.build_model(document, record, style)
            assert len(document.GetMaterials()) == material_count
            assert builder._prototype_materials(second) == first_materials
            assert first_materials['atom', 'C'] != first_materials['bond', 'C']
            assert document.DoUndo()
            assert len(document.GetMaterials()) == material_count
            assert first.IsAlive() and first.GetDocument() == document
            assert document.DoRedo()
            second = next(obj for obj in document.GetObjects() if obj != first)
            checks['document_wide_role_material_reuse_and_new_model_undo'] = True

            document.SetActiveObject(second, c4d.SELECTION_NEW)
            panel._bind_root(second)
            panel.SetString(ui.LABEL, '独立命名')
            panel.Command(ui.LABEL, c4d.BaseContainer())
            panel.SetInt32(ui.ELEMENT, ui.ELEMENTS.index('O'))
            panel.Command(ui.ELEMENT, c4d.BaseContainer())
            panel.SetColorField(ui.ELEMENT_COLOR, c4d.Vector(.9, .45, .12), 1., 1., c4d.DR_COLORFIELD_NO_BRIGHTNESS)
            panel.Command(ui.ELEMENT_COLOR, c4d.BaseContainer())
            panel.SetInt32(ui.BOND_ELEMENT, ui.ELEMENTS.index('H'))
            panel.Command(ui.BOND_ELEMENT, c4d.BaseContainer())
            panel.SetColorField(ui.BOND_COLOR, c4d.Vector(.14, .4, .8), 1., 1., c4d.DR_COLORFIELD_NO_BRIGHTNESS)
            panel.Command(ui.BOND_COLOR, c4d.BaseContainer())
            panel.SetInt32(ui.SPHERE_SEGMENTS, 40)
            panel.Command(ui.SPHERE_SEGMENTS, c4d.BaseContainer())
            panel.SetInt32(ui.CYLINDER_SEGMENTS, 18)
            panel.Command(ui.CYLINDER_SEGMENTS, c4d.BaseContainer())
            panel._live_due = 0.; panel.Timer(c4d.BaseContainer())
            current, edited = builder.read_model(second)
            assert current['name'] == '独立命名' and second.GetName() == '独立命名'
            assert edited['sphere_segments'] == 40 and edited['cylinder_segments'] == 18
            assert math.dist(edited['element_colors']['O'], [.9, .45, .12]) < 1e-6
            assert math.dist(edited['bond_element_colors']['H'], [.14, .4, .8]) < 1e-6
            assert builder.read_model(first)[1] == style
            assert len(document.GetMaterials()) == material_count + 2
            changed_materials = builder._prototype_materials(second)
            assert changed_materials['atom', 'O'] != first_materials['atom', 'O']
            assert changed_materials['bond', 'H'] != first_materials['bond', 'H']
            assert changed_materials['atom', 'C'] == first_materials['atom', 'C']
            for obj in builder._walk(second):
                if obj.GetName().startswith('球母体_'): assert obj[c4d.PRIM_SPHERE_SUB] == 40
                if obj.GetName().startswith('键母体_'): assert obj[c4d.PRIM_CYLINDER_SEG] == 18
            checks['live_name_independent_colors_segments_exact_root_binding'] = True

            ring = sorted({i for bond in record['bonds'] if bond['aromatic']
                           for i in (bond['a'], bond['b'])})
            oxygen = next(a['id'] for a in record['atoms'] if a['element'] == 'O')
            all_heavy = [a['id'] for a in record['atoms'] if a['element'] != 'H']
            group = display_geometry.make_plane_group(record, all_heavy)
            groups = {'1': {**group, 'color': [.2, .5, .85]}}
            panel.editor.set_record(record)
            panel.editor.groups = copy.deepcopy(groups); panel.editor.groups_dirty = True
            panel._live_due = 0.; panel.Timer(c4d.BaseContainer())
            assert builder.read_model(second)[1]['plane_groups'] == {}
            assert panel.editor.groups_dirty
            panel.SetString(ui.LABEL, '布局配置')
            panel._save_configuration()
            entry = panel.library.all()[0]
            assert entry['style']['plane_groups'] == groups
            assert entry['record']['atoms'] == record['atoms']
            first_config_id = entry['id']
            panel._save_configuration(save_as=True)
            assert [i['label'] for i in panel.library.all()] == ['布局配置', '布局配置 1']
            assert panel.configuration_id != first_config_id
            panel._apply_current()
            current, flattened = builder.read_model(second)
            assert not panel.editor.groups_dirty
            assert flattened['plane_groups'] == groups
            assert current['atoms'] == record['atoms']
            xyz = lambda i: [record['atoms'][i][a] for a in ('x', 'y', 'z')]
            pos = lambda i: flattened['position_overrides'].get(str(i), xyz(i))
            errors = [abs(math.dist(pos(b['a']), pos(b['b'])) - math.dist(xyz(b['a']), xyz(b['b']))) for b in record['bonds']]
            assert max(errors) < 1e-6
            for i in ring: assert pos(i) == xyz(i)
            oh = next(b['b'] if b['a'] == oxygen else b['a'] for b in record['bonds']
                      if oxygen in (b['a'], b['b']) and record['atoms'][b['b'] if b['a'] == oxygen else b['a']]['element'] == 'H')
            for i in all_heavy + [oh]:
                assert abs(sum((pos(i)[k] - group['origin'][k])*group['normal'][k] for k in range(3))) < .01
            checks['pending_planes_saved_explicitly_committed_rigid_bonds_OH_plane'] = {'max_bond_error': max(errors)}
            checks['same_structure_distinct_configuration_source_immutable'] = True

            panel.Command(ui.SPACE_FILL, c4d.BaseContainer()); panel._live_due = 0.; panel.Timer(None)
            assert builder.read_model(second)[1]['representation'] == 'space_fill'
            panel.Command(ui.RESET, c4d.BaseContainer()); panel._live_due = 0.; panel.Timer(None)
            assert builder.read_model(second)[1] == normalized_style()
            assert builder.read_model(second)[0]['atoms'] == before_record['atoms']
            checks['fill_and_reset_restore_default_without_changing_source'] = True

            asset = panel._prepare_asset(panel._record())
            loaded = c4d.documents.LoadDocument(asset, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)
            assert loaded is not None
            loaded_root = next(o for o in loaded.GetObjects() if builder.is_managed(o))
            asset_record, asset_style = builder.read_model(loaded_root)
            assert asset_record['atoms'] == record['atoms']
            builder.build_model(loaded, asset_record, asset_style, replace_root=loaded_root)
            checks['native_drag_asset_scene_load_and_safe_update'] = True
            save_path = ROOT / '测试/输出' / ('资源库验收_' + token + '.c4d')
            assert c4d.documents.SaveDocument(document, str(save_path), c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST, c4d.FORMAT_C4DEXPORT)
            report['document'] = str(save_path)
            report['status'] = 'PASS'
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            panel.backend.cancel(); panel._set_busy(False)
            if not original_doc.IsAlive():
                original_doc = startup_backup
                startup_backup = None
                c4d.documents.InsertBaseDocument(original_doc)
                checks['empty_startup_document_restored_from_clone'] = True
            c4d.documents.SetActiveDocument(original_doc)
            if loaded is not None: loaded.Flush()
            c4d.documents.KillDocument(document)
            for key, value in snapshot.items(): setattr(panel, key, value)
            panel._set_style(snapshot['style'])
            if snapshot['current_record']:
                panel._display(snapshot['current_record'])
                panel.editor.set_groups(editor_state[0])
                panel.editor.groups_dirty = editor_state[1]
                panel.editor.selected_ids = editor_state[2]
            else:
                panel.editor._image.bitmap = None; panel.editor._image.positions = {}
                panel.editor._image.light_bitmap = None; panel.editor._image.dark_bitmap = None
                panel.editor.groups = {}; panel.editor.groups_dirty = False
                panel.SetString(ui.LABEL, '')
            panel._set_editor_visible(snapshot['right_visible'])
            panel.HideElement(ui.EDITOR_GROUP, not snapshot['right_visible'])
            panel._set_pane_weights(); panel.LayoutChanged(ui.ROOT_LAYOUT)
            panel._rebuild_folders(); panel._cards(); panel.editor._image.Redraw()
            panel._status('验证完成' if report['status'] == 'PASS' else '验证发现问题，正在修复')
            c4d.EventAdd()
            assert c4d.documents.GetActiveDocument() == original_doc
            assert (original_doc.GetObjects(), original_doc.GetMaterials(), original_doc.GetDocumentName(), original_doc.GetDocumentPath()) == baseline
            checks['original_active_document_preserved'] = True
            if startup_backup is not None: startup_backup.Flush()
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    (ROOT / '测试/输出/资源库宿主验证.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return report
