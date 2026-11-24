"""Native panel callback checks in an owned temporary document, never render."""
import builtins
import copy
import json
import queue
import tempfile
from pathlib import Path
from time import perf_counter

import c4d
from scimol_c4d import browser_ui as ui, c4d_builder as builder
from scimol_c4d.library import Library
from scimol_c4d.usage import UsageStore
from scimol_c4d import atom_selector
from scimol_c4d.appearance_scale import to_physical

TOOL = Path(__file__).resolve().parents[1]


class Backend:
    def __init__(self):
        self.results = queue.Queue()
        self.generation = 0
        self.requests = []
    def cancel(self): self.generation += 1
    def submit(self, payload, context):
        self.cancel(); self.requests.append((copy.deepcopy(payload), context))
    def finish(self, result):
        self.results.put((self.generation,self.requests[-1][1],result,0.01))


def run():
    active = c4d.documents.GetActiveDocument()
    objects, materials = active.GetObjects(), active.GetMaterials()
    document_name, document_path = active.GetDocumentName(), active.GetDocumentPath()
    started_empty = not objects and not materials
    startup_backup = active.GetClone(c4d.COPYFLAGS_0)
    assert startup_backup is not None
    restored_from_clone = False
    previous = getattr(builtins, '_scimol_native_dialog_v1', None)
    if previous and previous.IsOpen(): previous.SetTimer(0)
    document = c4d.documents.BaseDocument()
    document.SetDocumentName('SciMol_实时交互验收')
    panel = None
    with tempfile.TemporaryDirectory() as folder:
        try:
            c4d.documents.InsertBaseDocument(document)
            c4d.documents.SetActiveDocument(document)
            panel = ui.BrowserDialog()
            panel.backend=Backend(); panel.preview_backend=Backend()
            panel.library=Library(Path(folder)/'library')
            panel.usage=UsageStore(Path(folder)/'usage')
            assert panel.Open(c4d.DLG_TYPE_ASYNC,defaultw=1000,defaulth=680)
            panel.SetTimer(0); panel.backend.cancel(); panel._set_busy(False)
            first=json.loads((TOOL/'测试/输出/苄醇三维.json').read_text(encoding='utf-8'))
            second=json.loads((TOOL/'测试/输出/水三维.json').read_text(encoding='utf-8'))
            panel.records=[first,second]; panel.view='test'; panel._cards()
            panel._select(0); root=panel.bound_root
            assert panel.available_elements==('C','H','O')
            assert panel.size_elements==panel.available_elements
            assert builder.read_model(root)[1]['element_scales']=={}
            assert abs(panel.GetFloat(ui.ELEMENT_SIZE)-1.)<1e-9
            assert len(document.GetObjects())==1
            panel._select(1)
            assert panel.bound_root==root and len(document.GetObjects())==1
            assert builder.read_model(root)[0]['structure_key']==second['structure_key']
            assert panel.available_elements==('H','O')
            assert panel.size_elements==panel.available_elements
            panel._select(0)
            assert panel.available_elements==('C','H','O')
            assert panel.size_elements==panel.available_elements
            nodes={obj.GetName():obj for obj in builder._walk(root)}
            start=perf_counter()
            panel.SetFloat(ui.ATOM_RADIUS,3); panel.Command(ui.ATOM_RADIUS,c4d.BaseContainer())
            panel._live_due=0; panel.Timer(c4d.BaseContainer())
            update_ms=(perf_counter()-start)*1000
            assert panel.bound_root==root
            assert all({o.GetName():o for o in builder._walk(root)}[name]==obj
                       for name,obj in nodes.items())
            assert abs(builder.read_model(root)[1]['atom_radius']-.65)<1e-9
            sizes=[]
            for value in (2.3, 2.4, 3.7, 1.8):
                panel.SetFloat(ui.ATOM_SLIDER,value); panel.Command(ui.ATOM_SLIDER,c4d.BaseContainer())
                panel._live_due=0; panel.Timer(c4d.BaseContainer())
                assert abs(panel.GetFloat(ui.ATOM_RADIUS)-value)<1e-9
                assert abs(builder.read_model(root)[1]['atom_radius']-to_physical('atom_radius',value))<1e-9
                assert all({o.GetName():o for o in builder._walk(root)}[name]==obj for name,obj in nodes.items())
                sizes.append(value)
            original_radii={element:nodes['球母体_'+element][c4d.PRIM_SPHERE_RAD]
                            for element in panel.available_elements}
            for element,value in (('H',.5),('C',2.1)):
                panel.SetInt32(ui.SIZE_ELEMENT,panel.available_elements.index(element))
                panel.Command(ui.SIZE_ELEMENT,c4d.BaseContainer())
                assert abs(panel.GetFloat(ui.ELEMENT_SIZE)-1.)<1e-9
                panel.SetFloat(ui.ELEMENT_SIZE_SLIDER,value); panel.Command(ui.ELEMENT_SIZE_SLIDER,c4d.BaseContainer())
                panel._live_due=0; panel.Timer(c4d.BaseContainer())
                assert abs(panel.GetFloat(ui.ELEMENT_SIZE)-value)<1e-9
                assert abs(nodes['球母体_'+element][c4d.PRIM_SPHERE_RAD]-original_radii[element]*value)<1e-9
                assert all({o.GetName():o for o in builder._walk(root)}[name]==obj for name,obj in nodes.items())
            scales=builder.read_model(root)[1]['element_scales'].copy()
            assert scales=={'H':.5,'C':2.1}
            assert abs(nodes['球母体_O'][c4d.PRIM_SPHERE_RAD]-original_radii['O'])<1e-9
            panel.SetFloat(ui.ATOM_RADIUS,4.1); panel.Command(ui.ATOM_RADIUS,c4d.BaseContainer())
            panel._live_due=0; panel.Timer(c4d.BaseContainer())
            style=builder.read_model(root)[1]
            assert style['element_scales']==scales
            assert abs(style['atom_radius']-to_physical('atom_radius',4.1))<1e-9
            unscaled=copy.deepcopy(style); unscaled['element_scales']={}
            for element in panel.available_elements:
                radius=nodes['球母体_'+element][c4d.PRIM_SPHERE_RAD]
                expected=builder._sphere_radius(unscaled,element)*scales.get(element,1.)
                assert abs(radius-expected)<1e-9
            assert all({o.GetName():o for o in builder._walk(root)}[name]==obj
                       for name,obj in nodes.items())
            legacy=copy.deepcopy(unscaled)
            legacy['element_radius_overrides']={'H':.5}
            panel._set_style(legacy)
            panel._queue_live(); panel._live_due=0; panel.Timer(c4d.BaseContainer())
            migrated=builder.read_model(root)[1]
            assert migrated['element_radius_overrides']=={}
            assert abs(nodes['球母体_H'][c4d.PRIM_SPHERE_RAD]-builder._sphere_radius(legacy,'H'))<1e-9
            panel.SetInt32(ui.SIZE_ELEMENT,panel.available_elements.index('H'))
            panel.Command(ui.SIZE_ELEMENT,c4d.BaseContainer())
            assert abs(round(migrated['element_scales']['H'],1)-panel.GetFloat(ui.ELEMENT_SIZE))<1e-9
            assert all({o.GetName():o for o in builder._walk(root)}[name]==obj
                       for name,obj in nodes.items())
            assert not root.GetUserDataContainer()
            assert all(not mat.GetUserDataContainer() for mat in document.GetMaterials())
            panel.SetString(ui.LABEL,'预览重命名'); panel.Command(ui.LABEL,c4d.BaseContainer())
            panel._live_due=0; panel.Timer(c4d.BaseContainer())
            assert root.GetName()=='预览重命名'
            assert all({o.GetName():o for o in builder._walk(root)}[name]==obj
                       for name,obj in nodes.items())
            panel.Command(ui.RIGHT_TOGGLE,c4d.BaseContainer())
            assert panel.editor.IsOpen() and panel.right_visible
            assert panel.editor.ring_options and panel.editor.ring_options[0]['label'].startswith('苯环')
            before_positions={a['id']:nodes['原子_%s_%s'%(a['element'],a['id'])].GetRelPos() for a in first['atoms']}
            panel.editor.SetInt32(atom_selector.RING_CENTER,1)
            panel.editor.Command(atom_selector.RING_CENTER,c4d.BaseContainer())
            panel._live_due=0; panel.Timer(c4d.BaseContainer())
            ring_ids=panel.editor.ring_options[0]['atom_ids']
            chosen_style=builder.read_model(root)[1]
            assert chosen_style['center_atom_ids']==ring_ids
            after_positions={a['id']:nodes['原子_%s_%s'%(a['element'],a['id'])].GetRelPos() for a in first['atoms']}
            assert sum((after_positions[i] for i in ring_ids),c4d.Vector()).GetLength()/len(ring_ids)<1e-7
            for a in before_positions:
                for b in before_positions:
                    assert abs((before_positions[a]-before_positions[b]).GetLength()-(after_positions[a]-after_positions[b]).GetLength())<1e-7
            panel.Command(ui.RIGHT_TOGGLE,c4d.BaseContainer())
            assert not panel.editor.IsOpen() and not panel.right_visible
            panel.SetString(ui.INPUT,'CCO'); panel.Command(ui.RESOLVE,c4d.BaseContainer())
            assert panel.search_pending and panel.GetString(ui.SEARCH_STATUS).startswith('正在搜索')
            assert panel.backend.requests[-1][0]['kind']=='auto'
            panel.backend.finish({'ok':True,'records':[second]}); panel.Timer(c4d.BaseContainer())
            assert not panel.search_pending and '找到 1' in panel.GetString(ui.SEARCH_STATUS)
            assert panel.bound_root==root
            requests_before=len(panel.backend.requests)
            panel.Command(ui.RESOLVE,c4d.BaseContainer())
            assert len(panel.backend.requests)==requests_before and not panel.search_pending
            assert '本地' in panel.GetString(ui.SEARCH_STATUS)
            assert panel.bound_root==root
            panel.Command(ui.FINISH,c4d.BaseContainer())
            frozen=builder.read_model(root)
            panel._select(0)
            assert panel.bound_root!=root and len(document.GetObjects())==2
            assert builder.read_model(root)==frozen
            assert panel.GetBool(ui.MATERIAL_INHERIT)
            centered=[]
            center_error=0.0
            for name in ('乙醇','乙酸'):
                record=json.loads((TOOL/'测试/输出'/('%s三维.json'%name)).read_text(encoding='utf-8'))
                panel.records=[record]; panel._cards(); panel._select(0)
                panel._set_style(copy.deepcopy(builder.DEFAULT_STYLE))
                panel._queue_live(); panel._live_due=0; panel.Timer(c4d.BaseContainer())
                atoms={a['id']:a for a in record['atoms']}
                heavy={i for i,a in atoms.items() if a['element']!='H'}
                degree={i:0 for i in heavy}
                for bond in record['bonds']:
                    if bond['a'] in heavy and bond['b'] in heavy:
                        degree[bond['a']]+=1; degree[bond['b']]+=1
                central=max((i for i in heavy if atoms[i]['element']=='C'),key=lambda i:degree[i])
                terminal=next(i for i in heavy if atoms[i]['element']=='C' and i!=central)
                native={o.GetName():o for o in builder._walk(panel.bound_root)}
                positions={i:native['原子_%s_%s'%(a['element'],i)].GetRelPos() for i,a in atoms.items()}
                assert positions[central].GetLength()<1e-7
                assert positions[terminal].x>0 and abs(positions[terminal].y)<1e-7 and abs(positions[terminal].z)<1e-7
                scale=builder.read_model(panel.bound_root)[1]['scale']
                original={i:c4d.Vector(a['x'],a['y'],a['z']) for i,a in atoms.items()}
                for a in atoms:
                    for b in atoms:
                        error=abs((positions[a]-positions[b]).GetLength()-(original[a]-original[b]).GetLength()*scale)
                        center_error=max(center_error,error)
                        assert error<1e-7
                centered.append(name)
            report={'status':'PASS','host_version':c4d.GetC4DVersion(),
                    'single_preview_switch':True,'finish_keeps_old_model':True,
                    'native_control_update_ms':update_ms,'rename_keeps_children':True,
                    'search_loading_and_unified_input':True,'separate_details_window':True,
                    'tenths_slider_values':sizes,'element_size_multipliers':scales,
                    'current_structure_element_menus':True,'legacy_element_size_migrated':True,
                    'ring_center_preserves_distances':True,'visible_user_data_removed':True,
                    'repeat_search_without_worker':True,'acyclic_center_and_horizontal_bond':centered,
                    'rigid_orientation_max_distance_error':center_error,
                    'scope':'Native callbacks; disposable document; no physical mouse or render.'}
        finally:
            try:
                if panel and panel.IsOpen(): panel.Close()
            finally:
                try:
                    if not active.IsAlive():
                        active = startup_backup
                        startup_backup = None
                        c4d.documents.InsertBaseDocument(active)
                        restored_from_clone = True
                    c4d.documents.SetActiveDocument(active)
                finally:
                    c4d.documents.KillDocument(document)
                    if startup_backup is not None: startup_backup.Flush()
                    if previous and previous.IsOpen(): previous.SetTimer(40)
    assert c4d.documents.GetActiveDocument()==active
    if restored_from_clone:
        assert started_empty
        assert not active.GetObjects() and not active.GetMaterials()
        assert (active.GetDocumentName(), active.GetDocumentPath())==(document_name,document_path)
    else:
        assert active.GetObjects()==objects and active.GetMaterials()==materials
    report['active_document_unchanged']=True
    report['startup_document_restored_from_clone']=restored_from_clone
    (TOOL/'测试/输出/实时预览交互宿主验证.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report
