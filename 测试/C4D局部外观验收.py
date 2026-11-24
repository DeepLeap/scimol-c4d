"""C4D-only checks using an in-memory document; never switches user documents."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import c4d
from scimol_c4d import c4d_builder as builder
from scimol_c4d.records import normalized_style, bond_key

ROOT = Path(__file__).resolve().parents[1]


def geometry(root):
    result = {"atoms": {}, "bonds": {}, "segments": {"sphere": set(), "cylinder": set()}}
    for obj in builder._walk(root):
        name, matrix = obj.GetName(), obj.GetMl()
        position = (matrix.off.x, matrix.off.y, matrix.off.z)
        if name.startswith("原子_"):
            result["atoms"][name] = (matrix.v1.GetLength(), position)
        elif name.startswith("键_"):
            result["bonds"][name] = (matrix.v1.GetLength(), matrix.v2.GetLength(),
                                    matrix.v3.GetLength(), position)
        if obj.CheckType(c4d.Osphere):
            result["segments"]["sphere"].add(obj[c4d.PRIM_SPHERE_SUB])
        elif obj.CheckType(c4d.Ocylinder):
            result["segments"]["cylinder"].add(obj[c4d.PRIM_CYLINDER_SEG])
    return result


def run():
    original_doc = c4d.documents.GetActiveDocument()
    original_objects = list(builder._document_objects(original_doc))
    original_materials = original_doc.GetMaterials()
    fixture = json.loads((ROOT / "测试/输出/苄醇三维.json").read_text(encoding="utf-8"))
    original_atoms = copy.deepcopy(fixture["atoms"])
    bond = next(b for b in fixture["bonds"] if b["order"] > 1)
    atom_id, edge_key = bond["a"], bond_key(bond["a"], bond["b"])
    atom_name = "原子_%s_%d" % (fixture["atoms"][atom_id]["element"], atom_id)
    edge_prefix = "键_%d_%d_" % (bond["a"], bond["b"])
    temporary = c4d.documents.BaseDocument()
    try:
        style = normalized_style({"sphere_segments": 32, "cylinder_segments": 18})
        root = builder.build_model(temporary, fixture, style)
        before = geometry(root)
        material_count = len(temporary.GetMaterials())
        style["atom_radius_overrides"] = {str(atom_id): .6}
        style["bond_radius_overrides"] = {edge_key: .16}
        assert builder.build_model(temporary, fixture, style, replace_root=root) == root
        after = geometry(root)
        for name, (radius, position) in before["atoms"].items():
            expected = radius * (2 if name == atom_name else 1)
            assert abs(after["atoms"][name][0] - expected) < 1e-8
            assert after["atoms"][name][1] == position
        changed_segments = 0
        for name, (width, length, depth, position) in before["bonds"].items():
            factor = 2 if name.startswith(edge_prefix) else 1
            new = after["bonds"][name]
            assert abs(new[0] - width * factor) < 1e-8
            assert abs(new[1] - length) < 1e-8
            assert abs(new[2] - depth * factor) < 1e-8
            assert new[3] == position
            changed_segments += int(factor == 2)
        assert changed_segments >= 2
        assert after["segments"] == {"sphere": {32}, "cylinder": {18}}
        assert len(temporary.GetMaterials()) == material_count
        stored_record, stored_style = builder.read_model(root)
        assert stored_record["atoms"] == original_atoms
        assert stored_style["atom_radius_overrides"] == {str(atom_id): .6}
        assert temporary.DoUndo()
        assert builder.read_model(root)[1]["atom_radius_overrides"] == {}
        assert temporary.DoRedo()
        assert builder.read_model(root)[1]["bond_radius_overrides"] == {edge_key: .16}
        report = {"status": "PASS", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                  "host_version": c4d.GetC4DVersion(), "atom_id": atom_id, "bond": edge_key,
                  "changed_bond_segments": changed_segments, "material_count": material_count,
                  "sphere_segments": 32, "cylinder_segments": 18, "undo_redo": True,
                  "scope": "Real C4D primitives and instances in an in-memory document; no physical mouse or rendering."}
    finally:
        temporary.Flush()
    assert c4d.documents.GetActiveDocument() == original_doc
    assert list(builder._document_objects(original_doc)) == original_objects
    assert original_doc.GetMaterials() == original_materials
    report["active_document_unchanged"] = True
    (ROOT / "测试/输出/局部外观宿主验证.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return report
