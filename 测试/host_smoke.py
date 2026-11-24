"""Explicit C4D-host smoke checks on a caller-owned disposable document.

Do not call this with the user's active document. No code runs on import.
"""

import c4d

from scimol_c4d.c4d_builder import build_model, is_managed, read_model


_ETHENE = {
    "name": "乙烯冒烟测试", "formula": "C2H4", "smiles": "C=C",
    "structure_key": "smoke-ethene", "source": "host-smoke",
    "stereo_status": "not_applicable", "warnings": [], "has_3d": True,
    "atoms": [
        {"id": 0, "element": "C", "x": -0.67, "y": 0, "z": 0, "charge": 0, "isotope": 0},
        {"id": 1, "element": "C", "x": 0.67, "y": 0, "z": 0, "charge": 0, "isotope": 0},
        {"id": 2, "element": "H", "x": -1.24, "y": 0.92, "z": 0, "charge": 0, "isotope": 0},
        {"id": 3, "element": "H", "x": -1.24, "y": -0.92, "z": 0, "charge": 0, "isotope": 0},
        {"id": 4, "element": "H", "x": 1.24, "y": 0.92, "z": 0, "charge": 0, "isotope": 0},
        {"id": 5, "element": "H", "x": 1.24, "y": -0.92, "z": 0, "charge": 0, "isotope": 0},
    ],
    "bonds": [
        {"a": 0, "b": 1, "order": 2, "aromatic": False},
        {"a": 0, "b": 2, "order": 1, "aromatic": False},
        {"a": 0, "b": 3, "order": 1, "aromatic": False},
        {"a": 1, "b": 4, "order": 1, "aromatic": False},
        {"a": 1, "b": 5, "order": 1, "aromatic": False},
    ],
}


def _descendants(root):
    node = root.GetDown()
    while node:
        yield node
        yield from _descendants(node)
        node = node.GetNext()


def _bond_instances(root):
    return [obj for obj in _descendants(root)
            if obj.CheckType(c4d.Oinstance) and obj.GetName().startswith("键_")]


def run_on_disposable_document(doc):
    """Return a small result dict, or raise on any regression.

    The caller must create an independent document and dispose of it afterwards.
    """
    if doc is None or doc == c4d.documents.GetActiveDocument():
        raise ValueError("冒烟测试必须使用独立文档，不能修改当前工程")
    single = build_model(doc, _ETHENE, {
        "bond_mode": "single", "bond_material": "uniform", "show_hydrogens": False,
    })
    assert is_managed(single)
    assert read_model(single)[0]["bonds"][0]["order"] == 2
    assert len(_bond_instances(single)) == 1
    atom_materials = {tag[c4d.TEXTURETAG_MATERIAL] for obj in _descendants(single)
                      if obj.GetName().startswith("球母体_") for tag in obj.GetTags()
                      if tag.CheckType(c4d.Ttexture)}
    bond_materials = {tag[c4d.TEXTURETAG_MATERIAL] for obj in _descendants(single)
                      if obj.GetName().startswith("键母体_") for tag in obj.GetTags()
                      if tag.CheckType(c4d.Ttexture)}
    assert atom_materials and bond_materials and atom_materials.isdisjoint(bond_materials)
    parent = c4d.BaseObject(c4d.Onull)
    parent.SetName("调用方父对象")
    doc.InsertObject(parent)
    single.InsertUnderLast(parent)
    single.SetRelPos(c4d.Vector(11, 12, 13))
    before_pos = single.GetRelPos()
    assert before_pos == c4d.Vector(11, 12, 13)
    user_tag = c4d.BaseTag(c4d.Tprotection)
    single.InsertTag(user_tag)
    multiple = build_model(doc, _ETHENE, {
        "bond_mode": "multiple", "bond_material": "uniform", "show_hydrogens": False,
    }, replace_root=single)
    assert multiple == single and is_managed(multiple)
    assert multiple.GetUp() == parent
    assert multiple.GetTag(c4d.Tprotection) == user_tag
    assert multiple.GetRelPos() == before_pos
    assert len(_bond_instances(multiple)) == 2
    assert read_model(multiple)[0]["bonds"][0]["order"] == 2
    assert doc.DoUndo()
    assert len(_bond_instances(single)) == 1
    assert read_model(single)[1]["bond_mode"] == "single"
    assert doc.DoRedo()
    assert len(_bond_instances(single)) == 2
    assert read_model(single)[1]["bond_mode"] == "multiple"
    assert single.GetUp() == parent and single.GetRelPos() == before_pos
    assert single.GetTag(c4d.Tprotection) == user_tag
    # Redone node materials and geometry must remain safe to update.
    multiple = build_model(doc, _ETHENE, {
        "bond_mode": "multiple", "bond_material": "uniform", "show_hydrogens": False,
    }, replace_root=single)
    # A user's child edit must never be silently discarded by a style update.
    strand = _bond_instances(multiple)[0]
    strand.SetRelPos(strand.GetRelPos() + c4d.Vector(1, 0, 0))
    try:
        build_model(doc, _ETHENE, {"bond_mode": "single", "show_hydrogens": False},
                    replace_root=multiple)
    except ValueError as exc:
        assert "手工修改" in str(exc)
    else:
        raise AssertionError("手工修改后的分子被静默覆盖")
    return {"single_segments": 1, "multiple_segments": 2,
            "atom_bond_materials_separate": True, "replace_preserved_bond_order": True,
            "manual_edit_protected": True, "root_identity_parent_tag_transform_preserved": True,
            "single_step_undo_redo_and_further_update": True}
