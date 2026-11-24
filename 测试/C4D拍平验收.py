"""Visible comparison in a new document; never renders or edits prior scenes."""

import builtins
import json
from pathlib import Path
import sys
import uuid

import c4d

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run(doc=None):
    from scimol_c4d import c4d_builder, display_geometry, ui
    from scimol_c4d.records import validate_record
    record = validate_record(json.loads((ROOT / "测试/输出/苄醇三维.json").read_text(encoding="utf-8")), require_3d=True)
    before = c4d.documents.GetActiveDocument()
    test_doc = c4d.documents.BaseDocument()
    test_doc.SetDocumentName("拍平对比.c4d")
    test_doc.GetActiveRenderData()[c4d.RDATA_RENDERENGINE] = 1036219
    c4d.documents.InsertBaseDocument(test_doc)
    c4d.documents.SetActiveDocument(test_doc)
    try:
        style = {"scale": 40, "bond_mode": "multiple", "bond_material": "uniform"}
        original = c4d_builder.build_model(test_doc, record, style)
        original.SetName("左 · 原始三维")
        flat_style = dict(style, position_overrides=display_geometry.flatten_overrides(record))
        flat = c4d_builder.build_model(test_doc, record, flat_style)
        flat.SetName("右 · 全部重原子拍平 · 氢保留方向")
        atoms = record["atoms"]
        heavy = {a["id"] for a in atoms if a["element"] != "H"}
        positions = {a["id"]: [a[k] for k in ("x", "y", "z")] for a in atoms}
        ring = display_geometry._planar_ring(heavy, positions, record["bonds"])
        _origin, normal = (ring[1], ring[2]) if ring else display_geometry._plane([positions[i] for i in heavy])
        n = c4d.Vector(normal[0], normal[1], -normal[2]).GetNormalized()
        hint = c4d.Vector(1, 0, 0) if abs(n.x) < .8 else c4d.Vector(0, 1, 0)
        x = (hint - n * hint.Dot(n)).GetNormalized()
        y = n.Cross(x).GetNormalized()
        for obj, offset in ((original, -160), (flat, 160)):
            obj.SetMl(c4d.Matrix(c4d.Vector(offset, 0, 0),
                                 c4d.Vector(x.x, y.x, n.x),
                                 c4d.Vector(x.y, y.y, n.y),
                                 c4d.Vector(x.z, y.z, n.z)))
        camera = c4d.BaseObject(1057516)
        camera.SetName("拍平对比视角")
        camera.SetRelPos(c4d.Vector(0, 100, -850))
        target = c4d.BaseObject(c4d.Onull)
        target.SetName("视角目标")
        test_doc.InsertObject(target)
        test_doc.InsertObject(camera)
        tag = c4d.BaseTag(c4d.Ttargetexpression)
        tag[1001] = target
        camera.InsertTag(tag)
        base_draw = test_doc.GetActiveBaseDraw()
        if base_draw:
            base_draw.SetSceneCamera(camera)
        test_doc.SetActiveObject(flat, c4d.SELECTION_NEW)
        path = ROOT / "测试/输出" / ("重原子拍平对比_" + uuid.uuid4().hex[:8] + ".c4d")
        if not c4d.documents.SaveDocument(test_doc, str(path), c4d.SAVEDOCUMENTFLAGS_0, c4d.FORMAT_C4DEXPORT):
            raise RuntimeError("无法保存拍平对比场景")
        test_doc.SetDocumentPath(str(path.parent))
        test_doc.SetDocumentName(path.name)
        ui.run(test_doc)
        panel = builtins._scimol_native_dialog_v1
        panel.backend.cancel()
        panel._set_busy(False)
        panel.Command(ui.READ_MODEL, c4d.BaseContainer())
        panel.Command(ui.ATOM_SELECT, c4d.BaseContainer())
        builtins._scimol_flatten_demo = {"doc": test_doc, "original": original, "flat": flat, "path": str(path)}
        c4d.EventAdd()
        print(json.dumps({"document": str(path), "selector_open": bool(panel.atom_selector and panel.atom_selector.IsOpen()),
                          "record_unchanged": c4d_builder.read_model(flat)[0] == record, "render_started": False}, ensure_ascii=False))
        return test_doc
    except Exception:
        if before and before.IsAlive():
            c4d.documents.SetActiveDocument(before)
        c4d.documents.KillDocument(test_doc)
        raise


if __name__ == "__main__":
    run()
