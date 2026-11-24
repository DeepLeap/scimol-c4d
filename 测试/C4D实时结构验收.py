"""Native primitive checks in a non-active document; no render or user edits."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
import c4d
from scimol_c4d import c4d_builder as builder
from scimol_c4d.records import normalized_style
from scimol_c4d.display_geometry import flatten_overrides

ROOT = Path(__file__).resolve().parents[1]


def positions(root):
    return {int(obj.GetName().rsplit('_',1)[1]): obj.GetRelPos()
            for obj in builder._walk(root) if obj.GetName().startswith('原子_')}


def carbon_radius(root):
    return next(obj[c4d.PRIM_SPHERE_RAD] for obj in builder._walk(root)
                if obj.GetName() == '球母体_C')


def run():
    active = c4d.documents.GetActiveDocument()
    objects, materials = active.GetObjects(), active.GetMaterials()
    fixture = json.loads((ROOT/'测试/输出/苄醇三维.json').read_text(encoding='utf-8'))
    original = copy.deepcopy(fixture['atoms'])
    temp = c4d.documents.BaseDocument()
    try:
        style = normalized_style({'representation':'continuous'})
        root = builder.build_model(temp,fixture,style)
        # Legacy models must remain editable after caps enter the signature.
        old_meta=builder._get_meta(root)
        old_meta.pop('signature_version',None)
        old_meta['signature']=builder._signature(root,include_caps=False)
        builder._put_meta(root,old_meta)
        cylinder=next(o for o in builder._walk(root) if o.CheckType(c4d.Ocylinder))
        cylinder[c4d.PRIM_CYLINDER_CAPS]=False
        try:
            builder.build_model(temp,fixture,style,replace_root=root)
        except ValueError:
            pass
        else:
            raise AssertionError('Legacy manual caps edit was overwritten')
        cylinder[c4d.PRIM_CYLINDER_CAPS]=True
        builder.build_model(temp,fixture,style,replace_root=root)
        assert builder._get_meta(root)['signature_version']==2
        count = len(temp.GetMaterials())
        radii = [carbon_radius(root)]
        for radius in (.65,1.):
            style['atom_radius']=radius
            builder.build_model(temp,fixture,style,replace_root=root)
            radii.append(carbon_radius(root))
        assert all(abs(actual-expected)<1e-8 for actual,expected in
                   zip(radii,[15.,43.875,85.]))
        style['bond_caps']=False
        builder.build_model(temp,fixture,style,replace_root=root)
        cylinders = [o for o in builder._walk(root) if o.CheckType(c4d.Ocylinder)]
        assert cylinders and all(not o[c4d.PRIM_CYLINDER_CAPS] for o in cylinders)
        style['bond_caps']=True
        style['position_overrides']=flatten_overrides(fixture)
        builder.build_model(temp,fixture,style,replace_root=root)
        before=positions(root)
        style['orientation']='xy'
        style['center_atom_ids']=[1]
        builder.build_model(temp,fixture,style,replace_root=root)
        after=positions(root)
        assert after[1].GetLength()<1e-8
        heavy=[a['id'] for a in fixture['atoms'] if a['element']!='H']
        # Near-planar ring coordinates stay rigid to retain their bond lengths.
        max_plane_offset=max(abs(after[i].z) for i in heavy)
        assert max_plane_offset < .01*style['scale']
        for a in before:
            for b in before:
                assert abs((before[a]-before[b]).GetLength()-(after[a]-after[b]).GetLength())<1e-7
        assert all(o[c4d.PRIM_CYLINDER_CAPS] for o in builder._walk(root)
                   if o.CheckType(c4d.Ocylinder))
        assert len(temp.GetMaterials())==count
        assert builder.read_model(root)[0]['atoms']==original
        assert temp.DoUndo() and temp.DoRedo()
        report={'status':'PASS','checked_at_utc':datetime.now(timezone.utc).isoformat(),
                'host_version':c4d.GetC4DVersion(),'continuous_C_radii':radii,
                'caps_toggle':True,'whole_rotation_preserves_all_distances':True,
                'legacy_signature_migration_preserves_manual_caps_edits':True,
                'chosen_atom_center':True,'flatten_then_XY':True,
                'xy_max_plane_offset_C4D_units':max_plane_offset,
                'materials_reused':True,'undo_redo':True,
                'scope':'Native geometry in non-active in-memory document; physical mouse not tested.'}
    finally:
        temp.Flush()
    assert active==c4d.documents.GetActiveDocument()
    assert active.GetObjects()==objects and active.GetMaterials()==materials
    report['active_document_unchanged']=True
    (ROOT/'测试/输出/实时结构宿主验证.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return report
