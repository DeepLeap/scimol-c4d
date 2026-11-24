"""Real Cinema 4D host verification for persistent RDKit worker, smart UI, presets, and rebind."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
import tempfile
import time

import c4d
from scimol_c4d import atom_selector, browser_ui as ui, c4d_builder as builder, search_index
from scimol_c4d.library import Library
from scimol_c4d.usage import UsageStore

ROOT = Path(__file__).resolve().parents[1]


def _pump_until(panel, predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        panel.Timer(c4d.BaseContainer())
        if predicate():
            return True
        time.sleep(0.02)
    raise TimeoutError("等待后台化学处理超时")


def _read_rs_base_color(mat):
    graph = mat.GetNodeMaterialReference().GetGraph(builder._NODE_SPACE)
    standard = graph.GetViewRoot().FindChild("scimol_standard")
    port = standard.GetInputs().FindChild(
        "com.redshift3d.redshift4c4d.nodes.core.standardmaterial.base_color"
    )
    vec = port.GetPortValue()
    if hasattr(vec, "x"):
        return [round(float(vec.x), 4), round(float(vec.y), 4), round(float(vec.z), 4)]
    return [round(float(vec[0]), 4), round(float(vec[1]), 4), round(float(vec[2]), 4)]


def run():
    active = c4d.documents.GetActiveDocument()
    before = (active.GetObjects(), active.GetMaterials()) if active else ([], [])
    backup = active.GetClone(c4d.COPYFLAGS_0) if active else None
    previous = getattr(builtins, "_scimol_native_dialog_v1", None)
    if previous and previous.IsOpen():
        previous.SetTimer(0)

    document = c4d.documents.BaseDocument()
    document.SetDocumentName("SciMol_智能特性宿主验收")
    panel = None
    with tempfile.TemporaryDirectory(prefix="scimol-smart-") as folder:
        try:
            c4d.documents.InsertBaseDocument(document)
            c4d.documents.SetActiveDocument(document)
            panel = ui.BrowserDialog()
            panel.library = Library(Path(folder) / "library")
            panel.usage = UsageStore(Path(folder) / "usage")
            assert panel.Open(c4d.DLG_TYPE_ASYNC, defaultw=1080, defaulth=700)
            panel.SetTimer(0)

            # Wait for initial builtin load so persistent worker is warm.
            _pump_until(panel, lambda: bool(panel.builtins) and not panel.busy, timeout=20.0)
            pid1 = panel.backend._daemon.process.pid

            # 1. Persistent worker reuse across smart local queries (THF, 葡萄糖, SMILES prefix)
            t0 = time.perf_counter()
            panel.SetString(ui.INPUT, "THF")
            panel.Command(ui.INPUT, c4d.BaseContainer())
            assert "四氢呋喃" in panel.GetString(ui.SEARCH_STATUS)
            panel.Command(ui.RESOLVE, c4d.BaseContainer())
            _pump_until(panel, lambda: not panel.search_pending and not panel.busy)
            thf_ms = round((time.perf_counter() - t0) * 1000, 1)
            assert len(panel.records) == 1 and panel.records[0]["name"] == "四氢呋喃"
            pid2 = panel.backend._daemon.process.pid
            assert pid2 == pid1

            t1 = time.perf_counter()
            panel.SetString(ui.INPUT, "葡萄糖")
            panel.Command(ui.RESOLVE, c4d.BaseContainer())
            _pump_until(panel, lambda: not panel.search_pending and not panel.busy)
            glucose_ms = round((time.perf_counter() - t1) * 1000, 1)
            assert panel.records[0]["formula"] == "C6H12O6"
            pid3 = panel.backend._daemon.process.pid
            assert pid3 == pid1

            # Verify smart formula normalization and rejection of abbreviations
            assert search_index.normalize_query_text("分子式：C₆H₁₂O₆") == "C6H12O6"
            assert search_index.is_valid_formula("C₆H₁₂O₆") is True
            assert search_index.is_valid_formula("THF") is False

            # Search THF again (cached/fast) and build real 3D model in C4D
            panel.SetString(ui.INPUT, "THF")
            panel.Command(ui.RESOLVE, c4d.BaseContainer())
            _pump_until(panel, lambda: not panel.search_pending and not panel.busy)
            t2 = time.perf_counter()
            panel._select(0)
            _pump_until(panel, lambda: panel.bound_root is not None and not panel.busy)
            thf_3d_ms = round((time.perf_counter() - t2) * 1000, 1)
            root = panel.bound_root
            assert root is not None and root.IsAlive()

            # 2. Stick mode & Redshift scientific color preset + real Undo check
            panel.Command(ui.STICK_MODE, c4d.BaseContainer())
            panel._live_due = 0.0
            panel.Timer(c4d.BaseContainer())
            stick_style = builder.read_model(root)[1]
            assert stick_style["representation"] == "continuous"
            assert abs(stick_style["atom_radius"] - 0.12) < 1e-6
            nodes = {o.GetName(): o for o in builder._walk(root)}
            assert abs(nodes["球母体_C"][c4d.PRIM_SPHERE_RAD] - 6.0) < 1e-5

            carbon_mat = builder._prototype_materials(root)[("atom", "C")]
            before_color = _read_rs_base_color(carbon_mat)
            assert before_color == [0.18, 0.18, 0.18]

            panel.SetInt32(ui.COLOR_PRESET, 2)  # Nature 银灰学术
            panel.Command(ui.COLOR_PRESET, c4d.BaseContainer())
            panel._live_due = 0.0
            panel.Timer(c4d.BaseContainer())
            carbon_mat = builder._prototype_materials(root)[("atom", "C")]
            nature_color = _read_rs_base_color(carbon_mat)
            assert nature_color == [0.32, 0.35, 0.39]

            assert document.DoUndo()
            carbon_mat = builder._prototype_materials(root)[("atom", "C")]
            undone_color = _read_rs_base_color(carbon_mat)
            assert undone_color == [0.18, 0.18, 0.18]
            assert document.DoRedo()
            carbon_mat = builder._prototype_materials(root)[("atom", "C")]
            assert _read_rs_base_color(carbon_mat) == [0.32, 0.35, 0.39]

            # 3. Context-aware controls & space_fill/ball_stick roundtrip
            panel.Command(ui.BALL_STICK, c4d.BaseContainer())
            panel._live_due = 0.0
            panel.Timer(c4d.BaseContainer())
            assert builder.read_model(root)[1]["representation"] == "ball_stick"
            panel.Command(ui.SPACE_FILL, c4d.BaseContainer())
            panel._live_due = 0.0
            panel.Timer(c4d.BaseContainer())
            assert builder.read_model(root)[1]["representation"] == "space_fill"
            if hasattr(panel, "IsEnabled"):
                assert not panel.IsEnabled(ui.BOND_SLIDER)
            panel.Command(ui.BALL_STICK, c4d.BaseContainer())
            panel._live_due = 0.0
            panel.Timer(c4d.BaseContainer())
            if hasattr(panel, "IsEnabled"):
                assert panel.IsEnabled(ui.BOND_SLIDER)

            # 4. Finish -> Rebind active model -> live update
            panel.Command(ui.FINISH, c4d.BaseContainer())
            assert not panel.session_active and panel.bound_root is None
            document.SetActiveObject(root, c4d.SELECTION_NEW)
            panel._poll_due = 0.0
            panel.Timer(c4d.BaseContainer())
            if hasattr(panel, "IsEnabled"):
                assert panel.IsEnabled(ui.REBIND_ACTIVE)
            panel.Command(ui.REBIND_ACTIVE, c4d.BaseContainer())
            assert panel.session_active and panel.bound_root == root
            panel.SetFloat(ui.ATOM_RADIUS, 4.0)
            panel.Command(ui.ATOM_RADIUS, c4d.BaseContainer())
            panel._live_due = 0.0
            panel.Timer(c4d.BaseContainer())
            rebound_style = builder.read_model(root)[1]
            assert abs(rebound_style["atom_radius"] - 0.825) < 1e-6
            nodes = {o.GetName(): o for o in builder._walk(root)}
            assert abs(nodes["球母体_C"][c4d.PRIM_SPHERE_RAD] - builder._sphere_radius(rebound_style, "C")) < 1e-4

            # 5. Structure details: SELECT_RING & INVERT_SELECT
            panel.Command(ui.RIGHT_TOGGLE, c4d.BaseContainer())
            assert panel.editor.IsOpen()
            assert len(panel.editor._image.positions) == 5
            panel.editor.Command(atom_selector.SELECT_RING, c4d.BaseContainer())
            assert len(panel.editor.selected_ids) == 5
            assert len(panel.editor.selected_bonds) == 5
            panel.editor.Command(atom_selector.INVERT_SELECT, c4d.BaseContainer())
            assert len(panel.editor.selected_ids) == 0

            daemon_proc = panel.backend._daemon.process
            report = {
                "status": "PASS",
                "host_version": c4d.GetC4DVersion(),
                "persistent_worker_pid_reused": pid1 == pid2 == pid3,
                "thf_warm_resolve_ms": thf_ms,
                "glucose_warm_resolve_ms": glucose_ms,
                "thf_3d_embed_ms": thf_3d_ms,
                "stick_mode_verified": True,
                "redshift_nature_preset_color": nature_color,
                "redshift_undo_color": undone_color,
                "context_aware_controls_verified": True,
                "rebind_active_verified": True,
                "selector_ring_and_invert_verified": True,
                "scope": "Real C4D 2027 host with live persistent RDKit backend and Redshift node graph.",
            }
        finally:
            try:
                if panel and panel.IsOpen():
                    panel.Close()
            finally:
                if active and not active.IsAlive() and backup is not None:
                    active = backup
                    backup = None
                    c4d.documents.InsertBaseDocument(active)
                if active and active.IsAlive():
                    c4d.documents.SetActiveDocument(active)
                c4d.documents.KillDocument(document)
                if backup is not None:
                    backup.Flush()
                if previous and previous.IsOpen():
                    previous.SetTimer(40)
    assert daemon_proc.poll() is not None, "关闭面板后常驻化学进程未退出"
    assert active.GetObjects() == before[0] and active.GetMaterials() == before[1]
    report["worker_cleanly_closed"] = True
    report["active_document_unchanged"] = True
    (ROOT / "测试/输出/智能特性宿主验收.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
