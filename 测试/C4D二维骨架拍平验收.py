"""Exercise depiction flattening on native instances in an owned document."""

import builtins
import copy
import importlib
import json
import math
from pathlib import Path
import runpy
import tempfile
import time

import c4d

ROOT = Path(__file__).resolve().parents[1]


def run():
    active = c4d.documents.GetActiveDocument()
    before = (active.GetObjects(), active.GetMaterials())
    backup = active.GetClone(c4d.COPYFLAGS_0)
    previous = getattr(builtins, '_scimol_native_dialog_v1', None)
    if previous and previous.IsOpen():
        previous.SetTimer(0)
    panel = None
    document = c4d.documents.BaseDocument()
    document.SetDocumentName('SciMol_二维骨架拍平验收')
    report = {'host_version': c4d.GetC4DVersion(), 'cases': [],
              'scope': 'Native controls and actual model transforms; no physical mouse or rendering.'}
    try:
        for name in ('hydrogen_layout', 'display_geometry', 'atom_selector', 'ui', 'browser_ui'):
            importlib.reload(importlib.import_module('scimol_c4d.' + name))
        from scimol_c4d import browser_ui as ui, atom_selector as ids
        from scimol_c4d import c4d_builder as builder, display_geometry as geometry
        from scimol_c4d.library import Library
        from scimol_c4d.usage import UsageStore
        from scimol_c4d.records import record_integrity, normalized_plane_groups
        from scimol_c4d.hydrogen_layout import collision_score
        backend = runpy.run_path(str(ROOT / '测试/C4D实时预览交互验收.py'))['Backend']
        c4d.documents.InsertBaseDocument(document)
        c4d.documents.SetActiveDocument(document)
        with tempfile.TemporaryDirectory(prefix='scimol-depiction-native-') as directory:
            panel = ui.BrowserDialog()
            panel.backend = backend()
            panel.preview_backend = backend()
            panel.library = Library(Path(directory) / 'library')
            panel.usage = UsageStore(Path(directory) / 'usage')
            assert panel.Open(c4d.DLG_TYPE_ASYNC, defaultw=960, defaulth=680)
            panel.SetTitle('SciMol_二维拍平测试面板')
            panel.SetTimer(0)
            panel.backend.cancel()
            panel._set_busy(False)

            def apply():
                panel._live_due = 0
                panel.Timer(c4d.BaseContainer())

            def xyz(record, root):
                nodes = {obj.GetName(): obj for obj in builder._walk(root)}
                return {atom['id']: nodes['原子_%s_%s' % (atom['element'], atom['id'])].GetRelPos()
                        for atom in record['atoms']}

            def identities(root):
                return {obj.GetName(): obj for obj in builder._walk(root) if obj != root}

            def unchanged_nodes(root, nodes):
                assert identities(root) == nodes

            def rigid_outside(record, original, current, selected):
                graph = {atom['id']: set() for atom in record['atoms'] if atom['id'] not in selected}
                for bond in record['bonds']:
                    a, b = bond['a'], bond['b']
                    if a in graph and b in graph:
                        graph[a].add(b)
                        graph[b].add(a)
                    if (a in selected) != (b in selected):
                        assert abs((original[a]-original[b]).GetLength() -
                                   (current[a]-current[b]).GetLength()) < 1e-5
                unseen = set(graph)
                while unseen:
                    start = min(unseen)
                    members = {start}
                    queue = [start]
                    unseen.remove(start)
                    for node in queue:
                        for neighbor in sorted(graph[node] & unseen):
                            unseen.remove(neighbor)
                            members.add(neighbor)
                            queue.append(neighbor)
                    for a in members:
                        for b in members:
                            assert abs((original[a]-original[b]).GetLength() -
                                       (current[a]-current[b]).GetLength()) < 1e-5

            for filename, selected in (('当前拍平案例.json', None),
                                       ('二维拍平长链.json', [4, 5, 6]),
                                       ('二维拍平分叉.json', [1, 3, 4])):
                record = json.loads((ROOT / '测试/输出' / filename).read_text(encoding='utf-8'))
                original_record = copy.deepcopy(record)
                integrity = record_integrity(record)
                panel.records = [record]
                panel._cards()
                panel._select(0)
                apply()
                panel._set_editor_visible(True)
                root = panel.bound_root
                nodes = identities(root)
                original = xyz(record, root)
                started = time.perf_counter()
                if selected is None:
                    panel.editor.Command(ids.ALL_FLATTEN, c4d.BaseContainer())
                else:
                    panel.editor.selected_ids = set(selected)
                    panel.editor.Command(ids.FLATTEN, c4d.BaseContainer())
                apply()
                flatten_update_ms = (time.perf_counter() - started) * 1000.
                assert panel.bound_root == root
                unchanged_nodes(root, nodes)
                current = xyz(record, root)
                affected = selected or [atom['id'] for atom in record['atoms'] if atom['element'] != 'H']
                coords = [[current[i].x, current[i].y, current[i].z] for i in affected]
                origin, normal = geometry._plane(coords)
                assert max(abs(geometry._dot(geometry._sub(point, origin), normal)) for point in coords) < 1e-5
                if selected is None:
                    scales = []
                    for bond in record['bonds']:
                        a, b = bond['a'], bond['b']
                        hotspots = record['thumbnail_atom_positions']
                        if str(a) in hotspots and str(b) in hotspots:
                            scales.append((current[a]-current[b]).GetLength() /
                                          math.dist(hotspots[str(a)], hotspots[str(b)]))
                    assert max(scales)-min(scales) < 1e-5
                    heavy = affected
                    for a in heavy:
                        for b in heavy:
                            if a != b:
                                assert (current[a]-current[b]).GetLength() > .05
                else:
                    rigid_outside(record, original, current, set(selected))
                    for endpoint in ([0, 9] if '长链' in filename else [0, 2, 5, 6]):
                        assert (current[endpoint]-original[endpoint]).GetLength() > .01
                style = copy.deepcopy(panel._get_style())
                assert style['position_overrides']
                def signed_neighbors(points, neighbors):
                    xyz_points = [[points[i].x, points[i].y, points[i].z] for i in neighbors]
                    vectors = [geometry._sub(point, xyz_points[-1]) for point in xyz_points[:3]]
                    return geometry._dot(vectors[0], geometry._cross(vectors[1], vectors[2]))

                all_graph = geometry._graph(original, record['bonds'])
                preserved_centers = 0
                for parent in affected:
                    neighbors = sorted(all_graph[parent])
                    if (len(neighbors) == 4 and record['atoms'][parent]['element'] == 'C' and
                            sum(record['atoms'][i]['element'] == 'H' for i in neighbors) == 1):
                        before_hand = signed_neighbors(original, neighbors)
                        after_hand = signed_neighbors(current, neighbors)
                        if abs(before_hand) > 1e-5:
                            assert before_hand * after_hand > 0, (parent, before_hand, after_hand)
                            preserved_centers += 1
                # Actual native H instance endpoints, rather than only pure
                # Python output, must retain every original X-H length.
                for bond in record['bonds']:
                    a, b = bond['a'], bond['b']
                    if record['atoms'][a]['element'] == 'H' or record['atoms'][b]['element'] == 'H':
                        assert abs((original[a]-original[b]).GetLength() -
                                   (current[a]-current[b]).GetLength()) < 1e-5
                clearance = None
                if selected is None:
                    _, source, _ = geometry._record_positions(record)
                    displayed = {int(key): value[:] for key, value
                                 in style['position_overrides'].items()}
                    graph = geometry._graph(source, record['bonds'])
                    heavy = {atom['id'] for atom in record['atoms'] if atom['element'] != 'H'}
                    elements = {atom['id']: atom['element'] for atom in record['atoms']}
                    _, raw_normal = geometry._plane([displayed[i] for i in sorted(heavy)])
                    legacy = copy.deepcopy(displayed)
                    # Reproduce the old first-neighbor H steering on the same
                    # fixed skeleton, so the score comparison isolates this fix.
                    for parent in sorted(heavy):
                        neighbors = sorted(graph[parent] & heavy)
                        old_axis = geometry._sub(source[neighbors[0]], source[parent]) if neighbors else None
                        new_axis = geometry._sub(displayed[neighbors[0]], displayed[parent]) if neighbors else None
                        for hydrogen in graph[parent] - heavy:
                            vector = geometry._sub(source[hydrogen], source[parent])
                            rotated = geometry._rotate_vector(vector, old_axis, new_axis) if neighbors else vector
                            if elements[parent] != 'C' and len(neighbors) <= 1:
                                projection = geometry._sub(rotated, [geometry._dot(rotated, raw_normal)*v
                                                                      for v in raw_normal])
                                rotated = [v*geometry._length(vector)/geometry._length(projection)
                                           for v in projection]
                            legacy[hydrogen] = [displayed[parent][i]+rotated[i] for i in range(3)]
                    before_score = collision_score(legacy, elements, record['bonds'])
                    after_score = collision_score(displayed, elements, record['bonds'])
                    actual = {i: [current[i].x/style['scale'], current[i].y/style['scale'],
                                  current[i].z/style['scale']] for i in current}
                    assert abs(collision_score(actual, elements, record['bonds']) - after_score) < 1e-6
                    assert after_score < before_score
                    clearance = {'old_first_neighbor_score': before_score,
                                 'new_score': after_score,
                                 'native_instances_match_score': True}
                assert record_integrity(panel.current_record) == integrity
                assert record == original_record
                assert panel._apply_flatten(selected)
                apply()
                repeated = xyz(record, root)
                assert max((current[i]-repeated[i]).GetLength() for i in current) < 1e-5
                unchanged_nodes(root, nodes)
                panel._save_configuration(save_as=True, name='测试二维配置')
                entry = next(item for item in panel.library.all() if item['id'] == panel.configuration_id)
                assert entry['style']['position_overrides'] == panel._get_style()['position_overrides']
                assert record_integrity(entry['record']) == integrity
                panel._restore_3d()
                apply()
                restored = xyz(record, root)
                assert max((original[i]-restored[i]).GetLength() for i in original) < 1e-5
                unchanged_nodes(root, nodes)
                report['cases'].append({'fixture': filename, 'selected': selected,
                                        'planar_selected': True, 'identity_preserved': True,
                                        'rigid_periphery_and_boundary': selected is not None,
                                        'repeat_no_drift': True, 'configuration_saved': True,
                                        'restore_original_3d': True, 'all_xh_lengths_preserved': True,
                                        'single_h_three_heavy_handedness_preserved': preserved_centers,
                                        'flatten_update_ms': round(flatten_update_ms, 2),
                                        'clearance': clearance})

            record = json.loads((ROOT / '测试/输出/二维拍平长链.json').read_text(encoding='utf-8'))
            original_record = copy.deepcopy(record)
            panel.records = [record]
            panel._select(0)
            apply()
            root = panel.bound_root
            nodes = identities(root)
            original = xyz(record, root)
            groups = {'1': {'atom_ids': [0, 1, 2, 3], 'origin': [0, 0, 0], 'normal': [0, 0, 1]},
                      '2': {'atom_ids': [6, 7, 8, 9], 'origin': [0, 0, 0], 'normal': [0, 1, 0]}}
            groups = normalized_plane_groups(groups)
            assert panel._apply_plane_groups(groups)
            apply()
            current = xyz(record, root)
            unchanged_nodes(root, nodes)
            for group in groups.values():
                coords = [[current[i].x, current[i].y, current[i].z] for i in group['atom_ids']]
                origin, normal = geometry._plane(coords)
                assert max(abs(geometry._dot(geometry._sub(point, origin), normal)) for point in coords) < 1e-5
            for a, b in ((3, 4), (4, 5), (5, 6)):
                assert abs((original[a]-original[b]).GetLength() -
                           (current[a]-current[b]).GetLength()) < 1e-5
            assert panel._get_style()['plane_groups'] == groups
            assert panel._apply_plane_groups(groups)
            apply()
            repeated = xyz(record, root)
            assert max((current[i]-repeated[i]).GetLength() for i in current) < 1e-5
            translated = {str(atom['id']): [atom['x']+1, atom['y']+2, atom['z']+3]
                          for atom in record['atoms']}
            configured = geometry.apply_plane_groups(record, groups, translated)
            configured_again = geometry.apply_plane_groups(record, groups, configured)
            assert max(math.dist(configured[key], configured_again[key]) for key in configured) < 1e-6
            style = panel._get_style()
            style['position_overrides'] = configured
            panel._set_style(style)
            panel._queue_live()
            apply()
            unchanged_nodes(root, nodes)
            positions = xyz(record, root)
            assert max((current[i]-positions[i]).GetLength() for i in current) < 1e-5
            panel._save_configuration(save_as=True, name='测试多平面配置')
            entry = next(item for item in panel.library.all() if item['id'] == panel.configuration_id)
            assert entry['style']['plane_groups'] == groups
            assert entry['style']['position_overrides'] == panel._get_style()['position_overrides']
            assert record == original_record
            panel._restore_3d()
            apply()
            restored = xyz(record, root)
            assert max((original[i]-restored[i]).GetLength() for i in original) < 1e-5
            unchanged_nodes(root, nodes)
            report['cases'].append({'fixture': '二维拍平长链.json', 'multiple_plane_groups': True,
                                    'groups_planar_after_rigid_carry': True, 'boundary_lengths_preserved': True,
                                    'identity_preserved': True, 'repeat_no_drift': True,
                                    'existing_display_overrides_reuse': True,
                                    'configuration_saved': True, 'restore_original_3d': True})
    finally:
        if panel and panel.IsOpen():
            panel.Close()
        if not active.IsAlive():
            active = backup
            backup = None
            c4d.documents.InsertBaseDocument(active)
        c4d.documents.SetActiveDocument(active)
        c4d.documents.KillDocument(document)
        if backup is not None:
            backup.Flush()
        if previous and previous.IsOpen():
            previous.SetTimer(40)
    assert (active.GetObjects(), active.GetMaterials()) == before
    report['active_document_unchanged'] = True
    report['status'] = 'PASS'
    (ROOT / '测试/输出/二维骨架拍平宿主验证.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return report
