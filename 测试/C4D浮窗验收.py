"""Two-phase native window check; lets C4D's event loop run between calls.

Run start(), then finish() in separate main-thread calls. No scene writes.
"""
import builtins
import json
from pathlib import Path
import tempfile

import c4d
from scimol_c4d import browser_ui as ui
from scimol_c4d.floating_windows import follower_position
from scimol_c4d.library import Library
from scimol_c4d.usage import UsageStore

ROOT = Path(__file__).resolve().parents[1]
KEY = '_scimol_float_check'


def start():
    if getattr(builtins, KEY, None):
        raise RuntimeError('Finish the previous floating-window check first')
    from runpy import run_path
    backend = run_path(str(ROOT/'测试/C4D实时预览交互验收.py'))['Backend']
    active = c4d.documents.GetActiveDocument()
    folder = tempfile.TemporaryDirectory(prefix='scimol-floating-')
    panel = ui.BrowserDialog()
    panel.backend = backend(); panel.preview_backend = backend()
    panel.library = Library(Path(folder.name)/'library')
    panel.usage = UsageStore(Path(folder.name)/'usage')
    state = {'panel': panel, 'folder': folder, 'document': active,
             'objects': active.GetObjects(), 'materials': active.GetMaterials()}
    setattr(builtins, KEY, state)
    try:
        assert panel.Open(c4d.DLG_TYPE_ASYNC, xpos=80, ypos=100, defaultw=800, defaulth=640)
        panel.SetTimer(0); panel.backend.cancel(); panel._set_busy(False)
        record = json.loads((ROOT/'测试/输出/苄醇三维.json').read_text(encoding='utf-8'))
        panel._display(record)
        panel._open_atom_selector_ready()
        assert panel._window_follower.is_running, 'Native windows were not identified'
        native = panel._window_follower.native
        parent, child = panel._window_follower._identities
        state.update(native=native, parent=parent, child=child,
                     left_width=panel.GetItemDim(ui.ROOT_LAYOUT)['w'])
        assert native.move(parent.hwnd, parent.frame.left+35, parent.frame.top+25)
        return {'status':'WAIT', 'follow_started':True, 'scene_changed':False}
    except Exception:
        panel._close_atom_selector(); panel.Close()
        folder.cleanup(); delattr(builtins, KEY)
        raise


def finish():
    state = getattr(builtins, KEY)
    panel = state['panel']
    try:
        native = state['native']
        parent = native.window(state['parent'].hwnd)
        child = native.window(state['child'].hwnd)
        assert parent and child and parent.hwnd != child.hwnd
        expected = follower_position(parent.frame, child.frame, native.workarea(parent.hwnd))
        assert (child.frame.left, child.frame.top) == expected
        assert child.frame.width == state['child'].frame.width
        assert child.frame.height == state['child'].frame.height
        left_before = panel.GetItemDim(ui.ROOT_LAYOUT)['w']
        panel.Command(ui.RIGHT_TOGGLE, c4d.BaseContainer())
        assert not panel.right_visible and not panel.editor.IsOpen()
        assert not panel._window_follower.is_running
        assert panel.GetItemDim(ui.ROOT_LAYOUT)['w'] == left_before == state['left_width']
        panel.Command(ui.RIGHT_TOGGLE, c4d.BaseContainer())
        assert panel._window_follower.is_running
        report = {'status':'PASS', 'host_version':c4d.GetC4DVersion(),
                  'separate_native_windows':True, 'follows_parent_move':True,
                  'child_size_preserved':True, 'closing_details_keeps_left_width':True,
                  'reopen_restarts_following':True,
                  'scope':'Native Win32 movement and C4D callbacks; no physical mouse or rendering.'}
    finally:
        panel._close_atom_selector(); panel.Close()
        state['folder'].cleanup(); delattr(builtins, KEY)
    active = c4d.documents.GetActiveDocument()
    assert active == state['document']
    assert active.GetObjects() == state['objects'] and active.GetMaterials() == state['materials']
    report['active_document_unchanged'] = True
    (ROOT/'测试/输出/浮窗宿主验证.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report
