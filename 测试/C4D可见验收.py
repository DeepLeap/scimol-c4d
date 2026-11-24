"""Run in Cinema 4D Script Manager: visible isolated demo, never renders.

Creates its own document; the user's prior project is kept open and unchanged.
"""

import builtins
import importlib
import json
from pathlib import Path
import sys
import uuid

import c4d

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def run(doc=None):
    from scimol_c4d import c4d_builder, ui
    from scimol_c4d.records import validate_record
    importlib.reload(c4d_builder)
    importlib.reload(ui)
    existing = getattr(builtins, "_scimol_native_dialog_v1", None)
    if existing and existing.IsOpen() and existing.busy:
        raise RuntimeError("分子面板正在处理结构，请完成或取消后再执行可见验收")
    record_path = PROJECT / "测试" / "输出" / "苄醇三维.json"
    with record_path.open(encoding="utf-8") as handle:
        record = validate_record(json.load(handle), require_3d=True)
    previous = c4d.documents.GetActiveDocument()
    previous_name = previous.GetDocumentName() if previous else None
    test_doc = c4d.documents.BaseDocument()
    test_doc.SetDocumentName("球棍可见验收.c4d")
    # This is the renderer ID actually reported by the running host's MCP.
    # Set it on our own document only; no render is started.
    test_doc.GetActiveRenderData()[c4d.RDATA_RENDERENGINE] = 1036219
    c4d.documents.InsertBaseDocument(test_doc)
    c4d.documents.SetActiveDocument(test_doc)
    try:
        print("[SciMol] 1/4 在独立文档生成单棍模型")
        single = c4d_builder.build_model(test_doc, record, {"bond_mode": "single", "bond_material": "uniform", "scale": 30})
        single.SetName("苄醇 · 单棍模式 · 统一键材质")
        single.SetRelPos(c4d.Vector(-140, 0, 0))
        print("[SciMol] 2/4 生成按真实键级显示的多键模型")
        multiple = c4d_builder.build_model(test_doc, record, {"bond_mode": "multiple", "bond_material": "uniform", "scale": 30})
        multiple.SetName("苄醇 · 多键模式 · 统一键材质")
        multiple.SetRelPos(c4d.Vector(140, 0, 0))
        camera = c4d.BaseObject(1057516)  # Redshift Camera, reported by ping.
        if camera is None:
            raise RuntimeError("当前宿主未提供 Redshift 相机")
        camera.SetName("验收视角")
        camera.SetRelPos(c4d.Vector(0, 60, -700))
        target = c4d.BaseObject(c4d.Onull)
        target.SetName("视角目标")
        test_doc.InsertObject(target)
        test_doc.InsertObject(camera)
        tag = c4d.BaseTag(c4d.Ttargetexpression)
        tag[1001] = target  # Target Expression link, documented by host tool.
        camera.InsertTag(tag)
        base_draw = test_doc.GetActiveBaseDraw()
        if base_draw:
            base_draw.SetSceneCamera(camera)
        test_doc.SetActiveObject(single, c4d.SELECTION_NEW)
        print("[SciMol] 3/4 保存独立场景，全部几何与材质内嵌")
        path = PROJECT / "测试" / "输出" / ("球棍可见验收_" + uuid.uuid4().hex[:8] + ".c4d")
        if not c4d.documents.SaveDocument(test_doc, str(path), c4d.SAVEDOCUMENTFLAGS_0, c4d.FORMAT_C4DEXPORT):
            raise RuntimeError("无法保存验收场景")
        test_doc.SetDocumentPath(str(path.parent))
        test_doc.SetDocumentName(path.name)
        print("[SciMol] 4/4 打开原生面板；从对象管理器读取所选模型")
        ui.run(test_doc)
        dialog = getattr(builtins, "_scimol_native_dialog_v1", None)
        if dialog and dialog.IsOpen():
            dialog.backend.cancel()
            dialog._set_busy(False)
            dialog._set_style(c4d_builder.read_model(single)[1])
            dialog._show_records([record], "model")
            dialog._select(0)
        c4d.EventAdd()
        report = {"document": str(path), "single_atoms": len(record["atoms"]),
                  "multiple_atoms": len(record["atoms"]), "previous_document": previous_name,
                  "panel_open": bool(dialog and dialog.IsOpen()),
                  "panel_reused": bool(existing and existing.IsOpen()), "render_started": False}
        (PROJECT / "测试" / "输出" / "可见验收结果.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return test_doc
    except Exception:
        if previous and previous.IsAlive():
            c4d.documents.SetActiveDocument(previous)
        c4d.documents.KillDocument(test_doc)
        raise


if __name__ == "__main__":
    run()
