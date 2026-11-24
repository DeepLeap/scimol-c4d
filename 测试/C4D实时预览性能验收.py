"""Run on the C4D main thread only; edits a disposable in-memory document."""

import copy
import json
from pathlib import Path
from time import perf_counter

import c4d
from scimol_c4d import c4d_builder as builder
from scimol_c4d.records import normalized_style

TOOL = Path(__file__).resolve().parents[1]


def _named(root):
    return {obj.GetName(): obj for obj in builder._walk(root)}


def _vector(vector):
    return tuple(round(float(v), 7) for v in (vector.x, vector.y, vector.z))


def _geometry(nodes):
    rows = {}
    for name, node in nodes.items():
        if name.startswith('原子_'):
            rows[name] = (_vector(node.GetRelPos()), _vector(node.GetRelScale()))
        elif name.startswith('键_') and not name.startswith('键母体_'):
            matrix = node.GetMl()
            rows[name] = tuple(_vector(v) for v in
                               (matrix.off, matrix.v1, matrix.v2, matrix.v3))
        elif name.startswith('球母体_'):
            rows[name] = (node[c4d.PRIM_SPHERE_RAD], node[c4d.PRIM_SPHERE_SUB])
        elif name.startswith('键母体_'):
            rows[name] = (node[c4d.PRIM_CYLINDER_RADIUS],
                          node[c4d.PRIM_CYLINDER_SEG], node[c4d.PRIM_CYLINDER_CAPS])
    return rows


def run():
    active = c4d.documents.GetActiveDocument()
    before_objects, before_materials = active.GetObjects(), active.GetMaterials()
    record = json.loads((TOOL / '测试/输出/苄醇三维.json').read_text(encoding='utf-8'))
    document = c4d.documents.BaseDocument()
    reference_doc = c4d.documents.BaseDocument()
    try:
        style = normalized_style({'representation': 'continuous',
                                  'inherit_materials': False})
        root = builder.build_model(document, record, style)
        root_id = id(root)
        nodes = _named(root)
        atom_name = next(name for name in nodes if name.startswith('原子_C_'))
        bond_name = next(name for name in nodes if name.startswith('键_'))
        material_before = builder._prototype_materials(root)
        material_count = len(document.GetMaterials())
        updates = []
        for radius, thickness, spacing in ((.40, .10, .22), (.7, .14, .3), (.3, .08, .18)):
            changed = normalized_style({**style, 'atom_radius': radius,
                                        'bond_radius': thickness,
                                        'bond_spacing': spacing})
            start = perf_counter()
            result = builder.build_model(document, record, changed, replace_root=root)
            updates.append((perf_counter() - start) * 1000)
            assert result is root and id(result) == root_id
            current = _named(root)
            assert current[atom_name] == nodes[atom_name]
            assert current[bond_name] == nodes[bond_name]
            style = changed
        assert builder._prototype_materials(root) == material_before
        assert len(document.GetMaterials()) == material_count
        reference = builder.build_model(reference_doc, record, style)
        assert _geometry(_named(root)) == _geometry(_named(reference)), (
            'live updates drifted from a fresh build')
        # Dedicated preview recolors its own material, without allocating a
        # replacement material for each slider/color action.
        recolored = normalized_style({**style,
                    'element_colors': {'C': [.40, .25, .20]}})
        builder.build_model(document, record, recolored, replace_root=root)
        after_recolor = builder._prototype_materials(root)
        assert after_recolor[('atom', 'C')] == material_before[('atom', 'C')]
        assert len(document.GetMaterials()) == material_count
        assert builder._get_material_spec(after_recolor[('atom', 'C')])[2] == (.4, .25, .2)
        assert document.DoUndo()
        assert builder._get_material_spec(builder._prototype_materials(root)[('atom','C')])[2] == (.18,.18,.18)
        assert document.DoRedo()
        assert builder._get_material_spec(builder._prototype_materials(root)[('atom','C')])[2] == (.4,.25,.2)
        assert builder._get_meta(root)['material_scope']
        # Independently generated dedicated preview gets a different scope.
        second = builder.build_model(document, record, recolored)
        assert (builder._prototype_materials(second)[('atom', 'C')] !=
                after_recolor[('atom', 'C')])
        assert builder._get_meta(second)['material_scope'] != builder._get_meta(root)['material_scope']
        # Inheritance shares one material per role/element. Changing its color
        # is visible through both models; fresh resources adopt that color.
        shared_style=normalized_style({'representation':'continuous'})
        shared_first=builder.build_model(document,record,shared_style)
        count_shared=len(document.GetMaterials())
        shared_second=builder.build_model(document,record,shared_style)
        assert len(document.GetMaterials())==count_shared
        shared_material=builder._prototype_materials(shared_first)[('atom','C')]
        assert builder._prototype_materials(shared_second)[('atom','C')]==shared_material
        new_color=normalized_style({**shared_style,'element_colors':{'C':[.2,.5,.8]}})
        builder.build_model(document,record,new_color,replace_root=shared_second)
        assert builder._prototype_materials(shared_second)[('atom','C')]==shared_material
        assert builder._get_material_spec(shared_material)[2]==(.2,.5,.8)
        inherited=builder.inherited_style(document,record,shared_style)
        assert inherited['element_colors']['C']==[.2,.5,.8]
        shared_third=builder.build_model(document,record,inherited)
        assert builder._prototype_materials(shared_third)[('atom','C')]==shared_material
        assert len(document.GetMaterials())==count_shared
        # A user edit to a child still stops both fast and rebuild paths.
        atom = _named(root)[atom_name]
        atom.SetRelScale(c4d.Vector(2))
        try:
            builder.build_model(document, record, style, replace_root=root)
        except ValueError:
            pass
        else:
            raise AssertionError('edited child was overwritten')
        report = {'status': 'PASS', 'host_version': c4d.GetC4DVersion(),
                  'fast_update_ms': updates, 'root_and_child_identity': True,
                  'private_material_color_reused': True,
                  'private_color_undo_redo': True,'shared_material_inheritance':True,
                  'separate_private_scopes': True, 'manual_edit_guard': True,
                  'scope': 'Disposable in-memory document; no render.'}
    finally:
        document.Flush()
        reference_doc.Flush()
    assert c4d.documents.GetActiveDocument() == active
    assert active.GetObjects() == before_objects and active.GetMaterials() == before_materials
    report['active_document_unchanged'] = True
    output = TOOL / '测试/输出/实时预览性能宿主验证.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report
