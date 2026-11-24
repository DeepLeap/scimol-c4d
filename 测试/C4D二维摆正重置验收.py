"""Native ring-center and reset callbacks in an owned temporary document."""
import builtins
import copy
import json
from pathlib import Path
import runpy
import tempfile

import c4d
from scimol_c4d import browser_ui as ui, c4d_builder as builder, atom_selector as ids
from scimol_c4d.library import Library
from scimol_c4d.usage import UsageStore
from scimol_c4d.records import DEFAULT_STYLE, DEPICTION_VERSION

ROOT = Path(__file__).resolve().parents[1]


def run():
    active = c4d.documents.GetActiveDocument()
    before = (active.GetObjects(), active.GetMaterials())
    backup = active.GetClone(c4d.COPYFLAGS_0)
    previous = getattr(builtins,'_scimol_native_dialog_v1',None)
    if previous and previous.IsOpen(): previous.SetTimer(0)
    backend = runpy.run_path(str(ROOT/'测试/C4D实时预览交互验收.py'))['Backend']
    document = c4d.documents.BaseDocument()
    document.SetDocumentName('SciMol_二维摆正重置验收')
    panel = None
    with tempfile.TemporaryDirectory(prefix='scimol-reset-') as directory:
        try:
            c4d.documents.InsertBaseDocument(document)
            c4d.documents.SetActiveDocument(document)
            panel = ui.BrowserDialog()
            panel.backend=backend(); panel.preview_backend=backend()
            panel.library=Library(Path(directory)/'library')
            panel.usage=UsageStore(Path(directory)/'usage')
            assert panel.Open(c4d.DLG_TYPE_ASYNC,defaultw=1000,defaulth=680)
            panel.SetTimer(0); panel.backend.cancel(); panel._set_busy(False)
            record=json.loads((ROOT/'测试/输出/咖啡因三维.json').read_text(encoding='utf-8'))
            panel.records=[record]; panel._cards(); panel._select(0)
            panel._open_atom_selector_ready()
            root=panel.bound_root
            nodes={o.GetName():o for o in builder._walk(root)}
            six=next(option['atom_ids'] for option in panel.editor.ring_options if len(option['atom_ids'])==6)
            five=next(option['atom_ids'] for option in panel.editor.ring_options if len(option['atom_ids'])==5)
            def positions():
                return {a['id']:nodes['原子_%s_%s'%(a['element'],a['id'])].GetRelPos() for a in record['atoms']}
            def center(atom_ids):
                points=positions()
                return sum((points[i] for i in atom_ids),c4d.Vector())/len(atom_ids)
            def apply():
                panel._live_due=0; panel.Timer(c4d.BaseContainer())
            assert center(six).GetLength()<1e-7
            assert center(five).GetLength()>1
            original=positions()
            panel.editor.SetInt32(ids.RING_CENTER,1+next(i for i,o in enumerate(panel.editor.ring_options) if o['atom_ids']==five))
            panel.editor.Command(ids.RING_CENTER,c4d.BaseContainer()); apply()
            assert center(five).GetLength()<1e-7
            panel.editor.Command(ids.RESET_CENTER,c4d.BaseContainer()); apply()
            assert center(six).GetLength()<1e-7
            oriented=positions()
            for a in original:
                for b in original:
                    assert abs((original[a]-original[b]).GetLength()-(oriented[a]-oriented[b]).GetLength())<1e-7
            pixel=panel.editor._image.positions
            edges=[b for b in record['bonds'] if b['a'] in six and b['b'] in six]
            assert min(abs(pixel[b['a']][1]-pixel[b['b']][1]) for b in edges)<1e-8
            assert record['depiction_version']==DEPICTION_VERSION
            for number,slider,key,_,_ in ui.PAIRS:
                changed=40 if 'segments' in key else 3.7
                panel.SetFloat(number,changed) if 'segments' not in key else panel.SetInt32(number,changed)
                panel.Command(number,c4d.BaseContainer()); apply()
                others=copy.deepcopy(panel._get_style())
                panel.Command(ui.SLIDER_RESETS[slider],c4d.BaseContainer()); apply()
                style=panel._get_style()
                assert style[key]==DEFAULT_STYLE[key]
                for other in ('atom_radius','bond_radius','bond_spacing','sphere_segments','cylinder_segments','element_scales'):
                    if other!=key: assert style[other]==others[other]
            panel.SetInt32(ui.SIZE_ELEMENT,panel.available_elements.index('C'))
            panel.Command(ui.SIZE_ELEMENT,c4d.BaseContainer())
            panel.SetFloat(ui.ELEMENT_SIZE,2.4); panel.Command(ui.ELEMENT_SIZE,c4d.BaseContainer()); apply()
            panel.Command(ui.SLIDER_RESETS[ui.ELEMENT_SIZE_SLIDER],c4d.BaseContainer()); apply()
            assert panel.GetFloat(ui.ELEMENT_SIZE)==1 and 'C' not in panel.style['element_scales']
            panel.editor.SetInt32(ids.BACKGROUND_SLIDER,83)
            panel.editor.Command(ids.BACKGROUND_SLIDER,c4d.BaseContainer())
            panel.editor.Command(ids.BACKGROUND_RESET,c4d.BaseContainer())
            assert panel.editor.background_white==0
            bond=next(iter(panel.editor._image.bonds))
            panel.editor.selected_ids={0}; panel.editor.selected_bonds={bond}
            panel._apply_local_appearance('atoms',[0],.55)
            panel._apply_local_appearance('bonds',[bond],.14); apply()
            panel.editor.Command(ids.LOCAL_ATOM_RESET,c4d.BaseContainer()); apply()
            assert '0' not in panel.style['atom_radius_overrides']
            assert panel.style['bond_radius_overrides'][bond]==.14
            panel.editor.Command(ids.LOCAL_BOND_RESET,c4d.BaseContainer()); apply()
            assert bond not in panel.style['bond_radius_overrides']
            for button in ui.SLIDER_RESETS.values():
                dim=panel.GetItemDim(button)
                assert 0<dim['w']<=40 and 0<dim['h']<=40
            for button in (ids.BACKGROUND_RESET,ids.LOCAL_ATOM_RESET,ids.LOCAL_BOND_RESET):
                dim=panel.editor.GetItemDim(button)
                assert 0<dim['w']<=40 and 0<dim['h']<=40
            assert all({o.GetName():o for o in builder._walk(root)}[name]==node for name,node in nodes.items())
            report={'status':'PASS','host_version':c4d.GetC4DVersion(),
                    'caffeine_auto_six_center':True,'explicit_five_center':True,
                    'rigid_distances_preserved':True,'two_d_ring_horizontal':True,
                    'nine_compact_reset_buttons':True,'each_reset_only_its_parameter':True,
                    'local_atom_bond_resets_independent':True,'mother_instance_identity_preserved':True,
                    'scope':'Native C4D callbacks and geometry; no physical mouse or rendering.'}
        finally:
            try:
                if panel and panel.IsOpen(): panel.Close()
            finally:
                if not active.IsAlive():
                    active=backup; backup=None
                    c4d.documents.InsertBaseDocument(active)
                c4d.documents.SetActiveDocument(active)
                c4d.documents.KillDocument(document)
                if backup is not None: backup.Flush()
                if previous and previous.IsOpen(): previous.SetTimer(40)
    assert (active.GetObjects(),active.GetMaterials())==before
    report['active_document_unchanged']=True
    (ROOT/'测试/输出/二维摆正重置宿主验证.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report
