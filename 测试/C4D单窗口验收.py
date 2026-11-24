"""Native panel state checks; only our test documents and test data are used."""

import builtins
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import c4d

ROOT = Path(__file__).resolve().parents[1]


def run():
    from scimol_c4d import ui, atom_selector, c4d_builder
    from scimol_c4d.library import Library
    from scimol_c4d.usage import UsageStore
    p = builtins._scimol_native_dialog_v1
    demo = builtins._scimol_flatten_demo
    document, root = demo['doc'], demo['flat']
    assert c4d.documents.GetActiveDocument() == document
    assert p.IsOpen() and isinstance(p.editor, c4d.gui.SubDialog)
    assert p.GetItemDim(ui.SCALE)['w'] == 0
    assert p.GetItemDim(ui.FLATTEN_ALL)['w'] == 0
    assert p.GetItemDim(ui.RESTORE_3D)['w'] == 0
    assert p.editor.GetItemDim(atom_selector.ALL_FLATTEN)['w'] > 0
    checks = {'single_window_embedding_scale_removed_plane_buttons_in_editor':True}
    record, style = c4d_builder.read_model(root)
    saved = (p.library, p.usage, copy.deepcopy(p.builtins), p.show_common, p.show_favorites)
    folder = ROOT / '测试/输出' / ('单窗口验收数据_' + uuid.uuid4().hex[:8])
    temporary = None
    try:
        p.library, p.usage = Library(folder), UsageStore(folder)
        p.builtins = [record]
        p.library.save(record, style, '验收苄醇')
        for common, favorites in ((True,False),(False,True),(True,True)):
            p.SetBool(ui.COMMON,common); p.SetBool(ui.FAVORITES,favorites)
            p.Command(ui.COMMON,c4d.BaseContainer()); p.Command(ui.FAVORITES,c4d.BaseContainer())
            assert {r['list_source'] for r in p.records} == ({'常用'} if common else set()) | ({'收藏'} if favorites else set())
        p._select(0)
        identity = p._record()['structure_key']
        p.SetBool(ui.COMMON,False); p.SetBool(ui.FAVORITES,False)
        p.Command(ui.COMMON,c4d.BaseContainer()); p.Command(ui.FAVORITES,c4d.BaseContainer())
        assert p.view == 'library_hidden' and p._record()['structure_key'] == identity
        checks['all_four_list_combinations_preserve_selection'] = True

        # Count real successful native Generate callbacks in another test doc.
        temporary = c4d.documents.BaseDocument()
        temporary.GetActiveRenderData()[c4d.RDATA_RENDERENGINE] = 1036219
        c4d.documents.InsertBaseDocument(temporary)
        c4d.documents.SetActiveDocument(temporary)
        p._show_records([record],'model'); p._select(0); p._set_style(style)
        p.Command(ui.GENERATE,c4d.BaseContainer())
        assert p.usage.ranked([])[0]['usage_count'] == 1
        first_root = temporary.GetActiveObject()
        p.Command(ui.UPDATE,c4d.BaseContainer())
        assert p.usage.ranked([])[0]['usage_count'] == 1
        p.Command(ui.GENERATE,c4d.BaseContainer())
        assert p.usage.ranked([])[0]['usage_count'] == 2
        second_root = temporary.GetActiveObject()
        checks['native_generate_counts_update_does_not'] = True
        first_style = c4d_builder.read_model(first_root)[1]
        temporary.SetActiveObject(first_root,c4d.SELECTION_NEW)
        p.SetBool(ui.EDIT_MODE,True); p.Command(ui.EDIT_MODE,c4d.BaseContainer())
        p.editor.selected_ids = {7}; p.editor._assign_group()
        first_draft = copy.deepcopy(p.editor.groups)
        temporary.SetActiveObject(second_root,c4d.SELECTION_NEW)
        p.Command(ui.READ_MODEL,c4d.BaseContainer())
        assert p.selector_root == second_root
        p.editor.selected_ids = {7}; p.editor._assign_group()
        p.editor.Command(atom_selector.APPLY_GROUPS,c4d.BaseContainer())
        assert c4d_builder.read_model(first_root)[1] == first_style
        assert len(c4d_builder.read_model(second_root)[1]['plane_groups']) > len(first_style['plane_groups'])
        checks['same_structure_copies_bind_to_correct_root'] = True
        temporary.SetActiveObject(first_root,c4d.SELECTION_NEW)
        p.Command(ui.READ_MODEL,c4d.BaseContainer())
        assert p.selector_root == first_root and p.editor.groups == first_draft
        assert p.editor.groups_dirty
        checks['per_model_unsubmitted_drafts_restored'] = True
        p._close_atom_selector()
        p.selector_drafts = []
        c4d.documents.SetActiveDocument(document)
        c4d.documents.KillDocument(temporary); temporary = None
    finally:
        if temporary is not None:
            c4d.documents.SetActiveDocument(document)
            c4d.documents.KillDocument(temporary)
        p.library, p.usage, p.builtins, p.show_common, p.show_favorites = saved
        p.SetBool(ui.COMMON,p.show_common); p.SetBool(ui.FAVORITES,p.show_favorites)
        document.SetActiveObject(root,c4d.SELECTION_NEW)
        p.Command(ui.READ_MODEL,c4d.BaseContainer())
        p.SetBool(ui.EDIT_MODE,True); p.Command(ui.EDIT_MODE,c4d.BaseContainer())

    selector = p.editor
    committed = copy.deepcopy(selector.groups)
    selector.selected_ids = {7}; selector._assign_group()
    pending = copy.deepcopy(selector.groups)
    p.SetBool(ui.EDIT_MODE,False); p.Command(ui.EDIT_MODE,c4d.BaseContainer())
    assert not p.GetBool(ui.EDIT_MODE)
    p.SetBool(ui.EDIT_MODE,True); p.Command(ui.EDIT_MODE,c4d.BaseContainer())
    assert selector.groups == pending
    assert c4d_builder.read_model(root)[1] == style
    checks['edit_toggle_preserves_unsubmitted_groups_without_moving_model'] = True
    selector.set_groups(committed)
    selector.selected_ids.clear(); selector._selection_changed()
    bounds = p.GetItemDim(ui.EDIT_MODE)
    offset = p.Screen2Local()
    msg = c4d.BaseContainer(c4d.BFM_GETCURSORINFO)
    msg.SetInt32(c4d.BFM_DRAG_SCREENX,bounds['x'] + bounds['w']//2 - offset['x'])
    msg.SetInt32(c4d.BFM_DRAG_SCREENY,bounds['y'] + bounds['h']//2 - offset['y'])
    result = c4d.BaseContainer()
    assert p.Message(msg,result) and '同一窗口' in result.GetString(c4d.RESULT_BUBBLEHELP)
    checks['native_hover_help_handler'] = True
    report = {'status':'PASS','finished_at_utc':datetime.now(timezone.utc).isoformat(),
              'c4d_version':c4d.GetC4DVersion(),'checks':checks,
              'main_dialog_open':p.IsOpen(), 'embedded_editor_bound':selector.IsOpen(),
              'physical_mouse_direction_popup_and_hover_tested':False,
              'render_started':False}
    (ROOT / '测试/输出/单窗口宿主验证.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    c4d.EventAdd()
    return report


if __name__ == '__main__':
    run()
