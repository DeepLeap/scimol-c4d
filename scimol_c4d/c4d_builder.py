"""Cinema 4D ball-and-stick builder. Call only on C4D's main thread.

The input structure is immutable: ``bond_mode='single'`` changes drawing only.
This module intentionally has no dependency on RDKit or network services.
"""

import hashlib
import json
import math
import uuid

import c4d
import maxon

from .records import DEFAULT_STYLE, atom_display_factor, bond_key, normalized_style
from .display_geometry import orient_display_positions


_MARKER = "SciMol model data v1"
_MATERIAL_MARKER = "SciMol material UUID"
_MATERIAL_SPEC_MARKER = "SciMol reusable material spec v1"
_PRIVATE_DATA_ID = 0x53434D4C  # SCML: private object/material data, not a plugin ID.
_PRIVATE_MARKER = "SciMol internal data v1"
_NODE_SPACE = maxon.Id("com.redshift3d.redshift4c4d.class.nodespace")
_COLORS = {
    "H": (0.93, 0.93, 0.93), "C": (0.18, 0.18, 0.18),
    "N": (0.12, 0.30, 0.85), "O": (0.85, 0.12, 0.10),
    "S": (0.95, 0.75, 0.08), "P": (0.95, 0.45, 0.10),
    "F": (0.30, 0.78, 0.25), "Cl": (0.20, 0.70, 0.20),
    "Br": (0.58, 0.18, 0.12), "I": (0.45, 0.22, 0.62),
}
_DEFAULT_STYLE = DEFAULT_STYLE


def _normal_style(style):
    return normalized_style(style)


def _color(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("颜色应为三个 0 到 1 的数字")
    numbers = [float(v) for v in value]
    if any(not math.isfinite(v) or v < 0 or v > 1 for v in numbers):
        raise ValueError("颜色应为三个 0 到 1 的数字")
    return numbers


def _normal_record(record):
    if not isinstance(record, dict) or not isinstance(record.get("atoms"), list):
        raise ValueError("无效分子结构")
    if not isinstance(record.get("bonds"), list):
        raise ValueError("分子缺少键列表")
    # Round-trip the user-facing fields through JSON; never persist foreign Python objects.
    record = json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))
    ids = set()
    for atom in record["atoms"]:
        atom_id = atom.get("id")
        if not isinstance(atom_id, (int, str)) or atom_id in ids:
            raise ValueError("原子 ID 缺失或重复")
        ids.add(atom_id)
        if not isinstance(atom.get("element"), str) or not atom["element"]:
            raise ValueError("原子元素缺失")
        for axis in ("x", "y", "z"):
            coordinate = float(atom[axis])
            if not math.isfinite(coordinate):
                raise ValueError("原子坐标无效")
            atom[axis] = coordinate
    if not record["atoms"]:
        raise ValueError("分子中没有原子")
    for bond in record["bonds"]:
        if bond.get("a") not in ids or bond.get("b") not in ids or bond["a"] == bond["b"]:
            raise ValueError("化学键指向无效原子")
        if bond.get("order") not in (1, 2, 3):
            raise ValueError("键级必须为 1、2 或 3；芳香键须先 Kekule 化")
    return record


def _private_entries(owner):
    raw = owner.GetDataInstance()[_PRIVATE_DATA_ID]
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("对象内部数据编号已被其他数据占用")
    if (not isinstance(payload, dict) or payload.get("marker") != _PRIVATE_MARKER or
            not isinstance(payload.get("entries"), dict)):
        raise ValueError("对象内部数据编号已被其他数据占用")
    return payload["entries"]


def _read_field(owner, marker):
    try:
        entries = _private_entries(owner)
    except ValueError:
        entries = {}
    if marker in entries:
        return entries[marker]
    # Compatibility with existing scenes, never a user-facing read operation.
    for desc_id, container in owner.GetUserDataContainer():
        if container[c4d.DESC_NAME] == marker:
            return owner[desc_id]
    return None


def _write_field(owner, marker, value):
    entries = _private_entries(owner)
    entries[marker] = value
    payload = {"marker": _PRIVATE_MARKER, "entries": entries}
    owner.GetDataInstance().SetString(_PRIVATE_DATA_ID, json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    for desc_id, container in list(owner.GetUserDataContainer()):
        if container[c4d.DESC_NAME] == marker:
            owner.RemoveUserData(desc_id)


def _get_meta(root):
    if not isinstance(root, c4d.BaseObject):
        return None
    try:
        data = json.loads(_read_field(root, _MARKER))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("marker") == _MARKER and data.get("schema") == 1 else None


def _put_meta(root, data):
    _write_field(root, _MARKER, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def _material_uuid(mat):
    value = _read_field(mat, _MATERIAL_MARKER)
    return str(value) if value is not None else None


def _set_material_uuid(mat):
    _write_field(mat, _MATERIAL_MARKER, uuid.uuid4().hex)


def _material_spec_key(key, color):
    """A role and exact requested color identify an interchangeable material."""
    return (str(key[0]), str(key[1]), tuple(_color(color)))


def _set_material_spec(mat, key, color, scope=None):
    graph = _material_graph_snapshot(mat)
    if graph is None:
        raise RuntimeError("材质图无法验证，不能注册共享材质")
    payload = {"schema": 1, "role": key[0], "key": key[1],
               "color": _color(color), "graph": graph, "scope": scope}
    _write_field(mat, _MATERIAL_SPEC_MARKER, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _get_material_spec(mat):
    if not _material_uuid(mat):
        return None
    try:
        payload = json.loads(_read_field(mat, _MATERIAL_SPEC_MARKER))
        key = (payload["role"], payload["key"])
        token = _material_spec_key(key, payload["color"])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    graph = _material_graph_snapshot(mat)
    if (payload.get("schema") != 1 or key[0] not in ("atom", "bond") or
            graph is None or payload.get("graph") != graph):
        return None
    return token


def _material_scope(mat):
    try:
        return json.loads(_read_field(mat, _MATERIAL_SPEC_MARKER)).get("scope")
    except (TypeError, ValueError, AttributeError):
        return None


def migrate_scene_user_data(document):
    """Remove only our legacy visible fields, preserving data and user fields."""
    markers = {_MARKER, _MATERIAL_MARKER, _MATERIAL_SPEC_MARKER}
    owners = list(document.GetMaterials())
    for root in document.GetObjects():
        owners.extend([root, *_walk(root)])
    pending = [(owner, [(desc_id, container[c4d.DESC_NAME], owner[desc_id])
                       for desc_id, container in owner.GetUserDataContainer()
                       if container[c4d.DESC_NAME] in markers]) for owner in owners]
    pending = [(owner, values) for owner, values in pending if values]
    # Check all destinations before changing any existing scene data.
    for owner, _values in pending: _private_entries(owner)
    if not pending: return 0
    document.StartUndo()
    try:
        for owner, values in pending:
            document.AddUndo(c4d.UNDOTYPE_CHANGE, owner)
            for _desc_id, marker, value in values: _write_field(owner, marker, value)
    finally:
        document.EndUndo()
    return sum(len(values) for _owner, values in pending)


def _material_graph_snapshot(mat):
    """Stable material input snapshot, including manual color/roughness edits.

    A C4D dirty counter is session-relative and unsuitable after save/reopen.
    This deliberately checks actual node IDs and input values instead.
    """
    node_material = mat.GetNodeMaterialReference()
    graph = node_material.GetGraph(_NODE_SPACE)
    if graph.IsNullValue():
        return None
    root = graph.GetViewRoot()
    nodes = root.GetChildren()
    node_ids = sorted(str(node.GetId()) for node in nodes if not node.IsNullValue())
    standard = root.FindChild("scimol_standard")
    if standard.IsNullValue():
        # Unknown graph layout means we cannot safely replace its object.
        return [node_ids, "unknown-standard-node"]
    inputs = standard.GetInputs()
    if inputs.IsNullValue():
        return [node_ids, "missing-inputs"]
    values = []
    for name in ("base_color", "metalness", "refl_roughness", "refl_ior"):
        port = inputs.FindChild(
            "com.redshift3d.redshift4c4d.nodes.core.standardmaterial." + name)
        values.append([name, str(port.GetPortValue()) if not port.IsNullValue() else None])
    output = root.FindChild("scimol_output")
    wires = []
    if not output.IsNullValue():
        output_inputs = output.GetInputs()
        if not output_inputs.IsNullValue():
            surface = output_inputs.FindChild("com.redshift3d.redshift4c4d.node.output.surface")
            if not surface.IsNullValue():
                wires = sorted(str(other.GetPath()) for other, _ in
                               surface.GetConnections(maxon.PORT_DIR.INPUT))
    return [node_ids, values, wires]


def is_managed(root):
    """Return whether this object itself is a SciMol-owned model root."""
    return _get_meta(root) is not None


def read_model(root):
    """Read the original chemical graph and display style from a model root."""
    data = _get_meta(root)
    if data is None:
        return None
    return data["record"], data["style"]


def _walk(node):
    child = node.GetDown()
    while child:
        yield child
        yield from _walk(child)
        child = child.GetNext()


def _vec_tuple(vec):
    return [round(float(vec.x), 7), round(float(vec.y), 7), round(float(vec.z), 7)]


def _tracks(node):
    result = []
    for track in node.GetCTracks():
        curve = track.GetCurve()
        result.append([track.GetName(), str(track.GetDescriptionID()),
                       curve.GetKeyCount() if curve else None])
    return result


def _signature(root, include_caps=True):
    """Conservatively detect edits below the movable model root."""
    rows = []
    for obj in _walk(root):
        matrix = obj.GetMl()
        row = [obj.GetType(), obj.GetName(), _vec_tuple(matrix.off),
               _vec_tuple(matrix.v1), _vec_tuple(matrix.v2), _vec_tuple(matrix.v3),
               obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR],
               obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER]]
        if obj.CheckType(c4d.Osphere):
            row.extend([obj[c4d.PRIM_SPHERE_RAD], obj[c4d.PRIM_SPHERE_SUB]])
        elif obj.CheckType(c4d.Ocylinder):
            row.extend([obj[c4d.PRIM_CYLINDER_RADIUS],
                        obj[c4d.PRIM_CYLINDER_HEIGHT], obj[c4d.PRIM_CYLINDER_SEG]])
            if include_caps: row.append(obj[c4d.PRIM_CYLINDER_CAPS])
        elif obj.CheckType(c4d.Oinstance):
            link = obj[c4d.INSTANCEOBJECT_LINK]
            row.append(link.GetName() if link else None)
            row.append(obj[c4d.INSTANCEOBJECT_RENDERINSTANCE_MODE])
        tags = []
        for tag in obj.GetTags():
            if tag.CheckType(c4d.Ttexture):
                mat = tag[c4d.TEXTURETAG_MATERIAL]
                tags.append([tag.GetType(), mat.GetName() if mat else None,
                             _material_uuid(mat) if mat else None,
                             _material_graph_snapshot(mat) if mat else None,
                             tag[c4d.TEXTURETAG_PROJECTION],
                             tag[c4d.TEXTURETAG_TILE],
                             tag[c4d.TEXTURETAG_OFFSETX],
                             tag[c4d.TEXTURETAG_OFFSETY]])
            elif tag.CheckType(c4d.Tphong):
                tags.append([tag.GetType(), tag[c4d.PHONGTAG_PHONG_ANGLELIMIT],
                             tag[c4d.PHONGTAG_PHONG_ANGLE]])
            else:
                tags.append([tag.GetType(), tag.GetName()])
        row.append(tags)
        row.append(_tracks(obj))
        for tag in obj.GetTags():
            row.append(_tracks(tag))
        rows.append(row)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def _node_material(doc, name, color):
    """Create a real Redshift Standard Material; caller owns the open undo list."""
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    if mat is None:
        raise MemoryError("无法创建材质")
    mat.SetName(name)
    _set_material_uuid(mat)
    graph = mat.GetNodeMaterialReference().CreateEmptyGraph(_NODE_SPACE)
    if graph.IsNullValue():
        raise RuntimeError("无法创建 Redshift 材质图")
    doc.InsertMaterial(mat)
    if not doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat):
        raise RuntimeError("无法记录材质撤销")
    settings = maxon.DataDictionary()
    # The material itself is new and already has a document undo item. Node
    # transaction undo items split redo when several materials are created;
    # restore the complete material through its NEWOBJ item instead.
    settings.Set(maxon.nodes.UndoMode, maxon.nodes.UNDO_MODE.NONE)
    with graph.BeginTransaction(settings) as transaction:
        out = graph.AddChild(maxon.Id("scimol_output"), maxon.Id(
            "com.redshift3d.redshift4c4d.node.output"))
        standard = graph.AddChild(maxon.Id("scimol_standard"), maxon.Id(
            "com.redshift3d.redshift4c4d.nodes.core.standardmaterial"))
        standard.GetOutputs().FindChild(
            "com.redshift3d.redshift4c4d.nodes.core.standardmaterial.outcolor").Connect(
            out.GetInputs().FindChild(
                "com.redshift3d.redshift4c4d.node.output.surface"))
        standard.GetInputs().FindChild(
            "com.redshift3d.redshift4c4d.nodes.core.standardmaterial.base_color"
        ).SetPortValue(maxon.Vector(*color))
        transaction.Commit()
    return mat


def _material_tag(obj, mat):
    tag = c4d.TextureTag()
    tag[c4d.TEXTURETAG_MATERIAL] = mat
    obj.InsertTag(tag)


def _basis_y(vector):
    y = vector.GetNormalized()
    reference = c4d.Vector(1, 0, 0) if abs(y.x) < 0.85 else c4d.Vector(0, 0, 1)
    x = reference - y * reference.Dot(y)
    x.Normalize()
    z = x.Cross(y)
    return x, y, z


def _bond_offsets(bond, positions, adjacency, atom_by_id, spacing):
    a, b = bond["a"], bond["b"]
    axis = (positions[b] - positions[a]).GetNormalized()
    heavy_hints = []
    hydrogen_hints = []
    for here, other in ((a, b), (b, a)):
        for neighbor in adjacency[here]:
            if neighbor != other:
                v = positions[neighbor] - positions[here]
                projected = v - axis * v.Dot(axis)
                if projected.GetLength() > 1e-7:
                    # A single local neighbor defines the bond plane. Summing
                    # symmetric neighbors (such as two H in ethene) cancels it.
                    (hydrogen_hints if atom_by_id[neighbor]["element"] == "H"
                     else heavy_hints).append(projected)
    hint = (heavy_hints or hydrogen_hints or [c4d.Vector(0)])[0]
    hint -= axis * hint.Dot(axis)
    if hint.GetLength() < 1e-7:
        reference = c4d.Vector(1, 0, 0) if abs(axis.x) < 0.85 else c4d.Vector(0, 0, 1)
        hint = reference - axis * reference.Dot(axis)
    hint.Normalize()
    count = int(bond["order"])
    if count == 1:
        return [c4d.Vector(0)]
    return [hint * ((i - (count - 1) / 2.0) * spacing) for i in range(count)]


def _make_segment(parent, prototype, start, end, name, radius_scale=1.0):
    obj = c4d.BaseObject(c4d.Oinstance)
    obj.SetName(name)
    obj[c4d.INSTANCEOBJECT_LINK] = prototype
    obj[c4d.INSTANCEOBJECT_RENDERINSTANCE_MODE] = c4d.INSTANCEOBJECT_RENDERINSTANCE_MODE_SINGLEINSTANCE
    obj.InsertUnderLast(parent)
    obj.SetMl(_segment_matrix(start, end, radius_scale))
    return obj


def _segment_matrix(start, end, radius_scale=1.0):
    delta = end - start
    length = delta.GetLength()
    if length < 1e-6:
        raise ValueError("化学键长度为零")
    x, y, z = _basis_y(delta)
    # The cylinder mother defines radius and segment count; scaling only X/Z
    # changes thickness while preserving the endpoint distance along Y.
    return c4d.Matrix(off=(start + end) * 0.5,
                      v1=x * radius_scale, v2=y * length,
                      v3=z * radius_scale)


def _validate_local_radius_targets(record, style):
    atoms = {str(atom["id"]) for atom in record["atoms"]}
    if set(style["atom_radius_overrides"]) - atoms:
        raise ValueError("局部原子半径引用了不存在的原子")
    if style["bond_radius_overrides"]:
        bonds = {bond_key(bond["a"], bond["b"]) for bond in record["bonds"]}
        if set(style["bond_radius_overrides"]) - bonds:
            raise ValueError("局部键粗细引用了不存在的化学键")
    if set(style["center_atom_ids"]) - {atom["id"] for atom in record["atoms"]}:
        raise ValueError("中心引用了不存在的原子")


def atom_radius_for_element(style, element):
    """Return this element's physical radius, before representation and scene scale."""
    return style.get("element_radius_overrides", {}).get(element, style["atom_radius"])


def _atom_factor(style, element, radius=None):
    return atom_display_factor(style, element, radius)


def _sphere_radius(style, element):
    radius = atom_radius_for_element(style, element)
    # Stored legacy absolute radii retain their original meaning until the UI
    # explicitly migrates them. New scales multiply the completed sphere size.
    multiplier = (1.0 if element in style.get("element_radius_overrides", {})
                  else style.get("element_scales", {}).get(element, 1.0))
    return radius * style["scale"] * _atom_factor(style, element, radius) * multiplier


def _atom_instance_scale(style, atom):
    """Preserve an atom override's old absolute physical radius semantics."""
    local = style["atom_radius_overrides"].get(str(atom["id"]))
    if local is None:
        return 1.0
    element = atom["element"]
    desired = local * _atom_factor(style, element)
    return desired * style["scale"] / _sphere_radius(style, element)


def _geometry_positions(record, style):
    """One coordinate calculation for a fresh hierarchy and live updates."""
    scale = style["scale"]
    display = {a["id"]: style["position_overrides"].get(
        str(a["id"]), [a["x"], a["y"], a["z"]]) for a in record["atoms"]}
    if set(style["position_overrides"]) - {str(a["id"]) for a in record["atoms"]}:
        raise ValueError("显示坐标引用了不存在的原子")
    display = orient_display_positions(record, display, style["orientation"],
                                       style["center_atom_ids"])
    return {atom_id: c4d.Vector(xyz[0] * scale, xyz[1] * scale, -xyz[2] * scale)
            for atom_id, xyz in display.items()}


def _visible_ball_cut(style, atom, offset_length):
    radius = _sphere_radius(style, atom["element"]) * _atom_instance_scale(style, atom)
    return math.sqrt(max(radius * radius - offset_length * offset_length, 0.0))


def _color_junction(start, end, offset, atom_a, atom_b, style):
    """Balance the two exposed bond lengths while retaining their outer ends."""
    length = (end - start).GetLength()
    cut_a = _visible_ball_cut(style, atom_a, offset.GetLength())
    cut_b = _visible_ball_cut(style, atom_b, offset.GetLength())
    # Buried bonds have no stable visible split. Preserve their center division.
    if cut_a + cut_b >= length:
        return (start + end) * 0.5
    division = (length + cut_a - cut_b) * 0.5
    epsilon = min(1e-6, length * 0.25)
    division = max(epsilon, min(length - epsilon, division))
    return start + (end - start) * (division / length)


def _bond_geometry(record, style, positions, visible_ids, bond_filter=None):
    """Yield the existing instance names and matrices in hierarchy order."""
    adjacency = {a["id"]: [] for a in record["atoms"]}
    atom_by_id = {a["id"]: a for a in record["atoms"]}
    for bond in record["bonds"]:
        adjacency[bond["a"]].append(bond["b"])
        adjacency[bond["b"]].append(bond["a"])
    for bond in record["bonds"]:
        a, b = bond["a"], bond["b"]
        if a not in visible_ids or b not in visible_ids:
            continue
        if bond_filter is not None and bond_key(a, b) not in bond_filter:
            continue
        local_radius = style["bond_radius_overrides"].get(
            bond_key(a, b), style["bond_radius"])
        radius_scale = local_radius / style["bond_radius"]
        start, end = positions[a], positions[b]
        offsets = (_bond_offsets(bond, positions, adjacency, atom_by_id,
                                 style["bond_spacing"] * style["scale"])
                   if style["bond_mode"] == "multiple" else [c4d.Vector(0)])
        for strand, offset in enumerate(offsets, 1):
            p, q = start + offset, end + offset
            name = "键_%s_%s_%s" % (a, b, strand)
            if style["bond_material"] == "uniform":
                yield name, ("bond", "uniform"), p, q, radius_scale
            else:
                mid = _color_junction(p, q, offset,
                                      atom_by_id[a], atom_by_id[b], style)
                yield name + "_A", ("bond", atom_by_id[a]["element"]), p, mid, radius_scale
                yield name + "_B", ("bond", atom_by_id[b]["element"]), mid, q, radius_scale


def _make_hierarchy(record, style, mats):
    scale = style["scale"]
    visible_atoms = [a for a in record["atoms"] if style["show_hydrogens"] or a["element"] != "H"]
    visible_ids = {a["id"] for a in visible_atoms}
    # RDKit uses right-handed coordinates; reflect Z for C4D's left-handed basis.
    positions = _geometry_positions(record, style)
    root = c4d.BaseObject(c4d.Onull)
    root.SetName("SciMol - " + str(record.get("name") or record.get("formula") or "分子"))
    atoms_group, bonds_group, templates = [c4d.BaseObject(c4d.Onull) for _ in range(3)]
    for node, name in ((atoms_group, "原子"), (bonds_group, "化学键"), (templates, "几何母体")):
        node.SetName(name)
        node.InsertUnderLast(root)
    if style["representation"] == "space_fill":
        bonds_group[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = c4d.MODE_OFF
        bonds_group[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = c4d.MODE_OFF
    templates[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = c4d.MODE_OFF
    templates[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = c4d.MODE_OFF

    sphere_prototypes = {}
    for element in sorted({a["element"] for a in visible_atoms}):
        proto = c4d.BaseObject(c4d.Osphere)
        proto.SetName("球母体_" + element)
        proto[c4d.PRIM_SPHERE_RAD] = _sphere_radius(style, element)
        proto[c4d.PRIM_SPHERE_SUB] = style["sphere_segments"]
        proto.InsertUnderLast(templates)
        proto.InsertTag(c4d.BaseTag(c4d.Tphong))
        _material_tag(proto, mats["atom", element])
        sphere_prototypes[element] = proto
    for atom in visible_atoms:
        obj = c4d.BaseObject(c4d.Oinstance)
        obj.SetName("原子_%s_%s" % (atom["element"], atom["id"]))
        obj[c4d.INSTANCEOBJECT_LINK] = sphere_prototypes[atom["element"]]
        obj[c4d.INSTANCEOBJECT_RENDERINSTANCE_MODE] = c4d.INSTANCEOBJECT_RENDERINSTANCE_MODE_SINGLEINSTANCE
        obj.InsertUnderLast(atoms_group)
        obj.SetRelPos(positions[atom["id"]])
        instance_scale = _atom_instance_scale(style, atom)
        if instance_scale != 1.0:
            obj.SetRelScale(c4d.Vector(instance_scale))

    cylinder_prototypes = {}
    material_keys = ([("bond", "uniform")] if style["bond_material"] == "uniform"
                     else [("bond", e) for e in sorted({a["element"] for a in visible_atoms})])
    for key in material_keys:
        proto = c4d.BaseObject(c4d.Ocylinder)
        proto.SetName("键母体_" + key[1])
        proto[c4d.PRIM_CYLINDER_RADIUS] = style["bond_radius"] * scale
        proto[c4d.PRIM_CYLINDER_HEIGHT] = 1.0
        proto[c4d.PRIM_CYLINDER_SEG] = style["cylinder_segments"]
        proto[c4d.PRIM_CYLINDER_CAPS] = style["bond_caps"]
        proto.InsertUnderLast(templates)
        proto.InsertTag(c4d.BaseTag(c4d.Tphong))
        _material_tag(proto, mats[key])
        cylinder_prototypes[key] = proto
    for name, key, p, q, radius_scale in _bond_geometry(record, style, positions, visible_ids):
        _make_segment(bonds_group, cylinder_prototypes[key], p, q, name, radius_scale)
    return root


def _material_specs(record, style):
    elements = {a["element"] for a in record["atoms"]
                if style["show_hydrogens"] or a["element"] != "H"}
    specs = {("atom", e): _color(style["element_colors"].get(e, _COLORS.get(e, (.7, .7, .7))))
             for e in elements}
    if style["bond_material"] == "uniform":
        specs["bond", "uniform"] = _color(style["bond_color"])
    else:
        specs.update({("bond", e): _color(style["bond_element_colors"].get(e, _COLORS.get(e, (.7, .7, .7))))
                      for e in elements})
    return specs


def inherited_style(doc, record, style):
    """Adopt existing shared element colors when choosing a fresh resource."""
    result = _normal_style(style)
    if not result["inherit_materials"]:
        return result
    wanted = set(_material_specs(record, result))
    found = set()
    for mat in doc.GetMaterials():
        token = _get_material_spec(mat)
        if token is None or _material_scope(mat) is not None:
            continue
        role, element, color = token
        key = (role, element)
        if key not in wanted or key in found:
            continue
        found.add(key)
        if role == "atom": result["element_colors"][element] = list(color)
        elif element == "uniform": result["bond_color"] = list(color)
        else: result["bond_element_colors"][element] = list(color)
    return result


def _prototype_materials(root):
    result = {}
    for obj in _walk(root):
        name = obj.GetName()
        if name.startswith("球母体_"):
            key = ("atom", name[len("球母体_"):])
        elif name.startswith("键母体_"):
            key = ("bond", name[len("键母体_"):])
        else:
            continue
        tag = obj.GetTag(c4d.Ttexture)
        if tag and tag[c4d.TEXTURETAG_MATERIAL]:
            result[key] = tag[c4d.TEXTURETAG_MATERIAL]
    return result


def _document_objects(doc):
    root = doc.GetFirstObject()
    while root:
        yield root
        yield from _walk(root)
        root = root.GetNext()


def _reusable_materials(doc, specs, scope=None):
    """Find unedited SciMol materials only inside this document.

    New materials use a self-contained spec plus graph fingerprint. Older
    materials have only a UUID; accept them only through an unedited managed
    model whose stored style and prototype links prove the same specification.
    """
    wanted = {_material_spec_key(key, color): key for key, color in specs.items()}
    found = {}
    mat = doc.GetFirstMaterial()
    while mat:
        if mat.GetDocument() == doc:
            try:
                token = _get_material_spec(mat)
            except Exception:
                token = None
            if (token in wanted and _material_scope(mat) == scope and
                    wanted[token] not in found):
                found[wanted[token]] = mat
        mat = mat.GetNext()
    if len(found) == len(specs):
        return found
    if scope is not None:
        # Dedicated preview materials never borrow from another model, even
        # from a legacy model with the same color and element name.
        return found
    for root in _document_objects(doc):
        meta = _get_meta(root)
        if meta is None:
            continue
        try:
            if meta.get("signature") != _signature(root):
                continue
            previous_specs = _material_specs(meta["record"], _normal_style(meta["style"]))
            prototypes = _prototype_materials(root)
        except Exception:
            continue
        for key, mat in prototypes.items():
            if (key in specs and key not in found and
                    previous_specs.get(key) == specs[key] and
                    mat.GetDocument() == doc and _material_uuid(mat) and
                    _material_scope(mat) is None):
                found[key] = mat
        if len(found) == len(specs):
            break
    return found


def _material_referenced_by_tags(doc, material):
    """Conservatively check every tag parameter before deleting a material.

    A texture tag is the normal SciMol link, but a user may also have linked an
    imported material from another tag. An unreadable tag keeps the material.
    """
    for obj in _document_objects(doc):
        for tag in obj.GetTags():
            try:
                if (tag.CheckType(c4d.Ttexture) and
                        tag[c4d.TEXTURETAG_MATERIAL] == material):
                    return True
                for _settings, param_id, _group in tag.GetDescription(
                        c4d.DESCFLAGS_DESC_NONE):
                    # Description headings and scalar controls are not link
                    # parameters; some cannot be read via tag[param_id] at all.
                    # DescID levels are zero-indexed and the last level owns
                    # the parameter's datatype.
                    if (param_id.GetDepth() < 1 or
                            param_id[param_id.GetDepth() - 1].dtype !=
                            c4d.DTYPE_BASELISTLINK):
                        continue
                    try:
                        if tag[param_id] == material:
                            return True
                    except Exception:
                        # A real link field that cannot be inspected could
                        # still point at this material. Keep it rather than
                        # deleting an unknown user's reference.
                        return True
            except Exception:
                return True
    return False


def _material_used_outside_root(doc, root, material):
    """A dedicated preview color may change only when no other object uses it."""
    inside = [root, *_walk(root)]
    for obj in _document_objects(doc):
        if obj in inside:
            continue
        for tag in obj.GetTags():
            try:
                if (tag.CheckType(c4d.Ttexture) and
                        tag[c4d.TEXTURETAG_MATERIAL] == material):
                    return True
                for _settings, param_id, _group in tag.GetDescription(
                        c4d.DESCFLAGS_DESC_NONE):
                    if (param_id.GetDepth() < 1 or
                            param_id[param_id.GetDepth() - 1].dtype !=
                            c4d.DTYPE_BASELISTLINK):
                        continue
                    try:
                        if tag[param_id] == material:
                            return True
                    except Exception:
                        return True
            except Exception:
                return True
    return False


def _set_material_color(mat, color, record_undo=True):
    """Change only an owned Redshift Standard Material base color."""
    graph = mat.GetNodeMaterialReference().GetGraph(_NODE_SPACE)
    if graph.IsNullValue():
        raise RuntimeError("预览材质图不可用")
    standard = graph.GetViewRoot().FindChild("scimol_standard")
    if standard.IsNullValue():
        raise RuntimeError("预览材质不是标准材质")
    port = standard.GetInputs().FindChild(
        "com.redshift3d.redshift4c4d.nodes.core.standardmaterial.base_color")
    if port.IsNullValue():
        raise RuntimeError("预览材质颜色端口不可用")
    settings = maxon.DataDictionary()
    settings.Set(maxon.nodes.UndoMode,
                 maxon.nodes.UNDO_MODE.ADD if record_undo else maxon.nodes.UNDO_MODE.NONE)
    with graph.BeginTransaction(settings) as transaction:
        port.SetPortValue(maxon.Vector(*_color(color)))
        transaction.Commit()


def deduplicate_imported_materials(doc, imported_roots, imported_materials):
    """Reconnect one native asset drop to existing, identical SciMol materials.

    Only the explicitly passed imported roots/tokens may change. A model whose
    descendants were manually edited is refused before the undo transaction.
    Imported material deletion requires an unedited reusable spec and no tag
    references anywhere in the current document after reconnecting.
    """
    if not isinstance(doc, c4d.documents.BaseDocument):
        raise ValueError("必须提供 C4D 文档")
    roots = list(imported_roots)
    imported = list(imported_materials)
    if len(set(roots)) != len(roots) or len(set(imported)) != len(imported):
        raise ValueError("导入对象列表有重复项")
    for root in roots:
        meta = _get_meta(root)
        if (meta is None or root.GetDocument() != doc or
                meta.get("signature") != _signature(root)):
            raise ValueError("拖入的分子内部或材质已手工修改，不能自动替换材质")
    all_materials = []
    material = doc.GetFirstMaterial()
    while material:
        all_materials.append(material)
        material = material.GetNext()
    if any(material.GetDocument() != doc or material not in all_materials
           for material in imported):
        raise ValueError("导入材质不属于当前文档")
    imported_set = set(imported)
    # Compare role, element/uniform key, exact requested color and the actual
    # Redshift node graph. Names alone are not evidence of equivalence.
    existing = {}
    for material in all_materials:
        if material in imported_set:
            continue
        token = _get_material_spec(material)
        if token is not None:
            existing.setdefault((token, _material_scope(material),
                                 json.dumps(_material_graph_snapshot(material),
                                            ensure_ascii=False, sort_keys=True)), material)
    replacements = {}
    for material in imported:
        token = _get_material_spec(material)
        if token is None:
            continue
        graph = _material_graph_snapshot(material)
        canonical = existing.get((token, _material_scope(material),
                                  json.dumps(graph, ensure_ascii=False,
                                             sort_keys=True)))
        if canonical is not None:
            replacements[material] = canonical
    changes = []
    touched_roots = []
    for root in roots:
        root_changes = []
        for obj in _walk(root):
            for tag in obj.GetTags():
                if tag.CheckType(c4d.Ttexture):
                    old = tag[c4d.TEXTURETAG_MATERIAL]
                    if old in replacements:
                        root_changes.append((tag, old, replacements[old]))
        if root_changes:
            touched_roots.append((root, _get_meta(root)))
            changes.extend(root_changes)
    if not changes and not replacements:
        return {"relinked": 0, "removed": 0}
    c4d.StopAllThreads()
    if not doc.StartUndo():
        raise RuntimeError("无法开始材质去重撤销记录")
    removed = []
    try:
        for tag, old, canonical in changes:
            if not doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, tag):
                raise RuntimeError("无法记录材质标签撤销")
            tag[c4d.TEXTURETAG_MATERIAL] = canonical
        for root, previous_meta in touched_roots:
            if not doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, root):
                raise RuntimeError("无法记录分子元数据撤销")
            updated = dict(previous_meta)
            updated["signature"] = _signature(root)
            updated["signature_version"] = 2
            _put_meta(root, updated)
        for material in replacements:
            if _material_referenced_by_tags(doc, material):
                continue
            if not doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, material):
                raise RuntimeError("无法记录重复材质撤销")
            material.Remove()
            removed.append(material)
        c4d.EventAdd()
        return {"relinked": len(changes), "removed": len(removed)}
    except Exception:
        for material in removed:
            doc.InsertMaterial(material)
        for tag, old, _canonical in reversed(changes):
            tag[c4d.TEXTURETAG_MATERIAL] = old
        for root, previous_meta in touched_roots:
            _put_meta(root, previous_meta)
        raise
    finally:
        doc.EndUndo()


_LIVE_TOPOLOGY_KEYS = frozenset(("show_hydrogens", "bond_mode", "bond_material",
                                 "inherit_materials", "element_colors",
                                 "bond_element_colors", "bond_color"))


def _direct_children(parent):
    child = parent.GetDown()
    while child:
        yield child
        child = child.GetNext()


def _live_plan(root, record, previous, style):
    """Prepare primitive edits without allocating replacement C4D objects.

    None means the saved hierarchy does not have the expected layout; the
    ordinary guarded rebuild can handle it. This runs only after signature
    validation, so no user-edited child is ever silently modified.
    """
    if any(previous[key] != style[key] for key in _LIVE_TOPOLOGY_KEYS):
        return None
    if (previous["representation"] == "space_fill") != (style["representation"] == "space_fill"):
        return None
    groups = {obj.GetName(): obj for obj in _direct_children(root)}
    if set(groups) != {"原子", "化学键", "几何母体"}:
        return None
    atoms = {obj.GetName(): obj for obj in _direct_children(groups["原子"])}
    bonds = {obj.GetName(): obj for obj in _direct_children(groups["化学键"])}
    prototypes = {obj.GetName(): obj for obj in _direct_children(groups["几何母体"])}
    visible_atoms = [a for a in record["atoms"]
                     if style["show_hydrogens"] or a["element"] != "H"]
    visible_ids = {a["id"] for a in visible_atoms}
    expected_atoms = {"原子_%s_%s" % (a["element"], a["id"]) for a in visible_atoms}
    expected_prototypes = ({"球母体_" + a["element"] for a in visible_atoms} |
                           {"键母体_" + key[1] for key in _material_specs(record, style)
                            if key[0] == "bond"})
    if set(atoms) != expected_atoms or set(prototypes) != expected_prototypes:
        return None
    position_keys = {"scale", "position_overrides", "orientation", "center_atom_ids"}
    positions_changed = any(previous[key] != style[key] for key in position_keys)
    atom_shape_changed = any(previous[key] != style[key] for key in
                             ("scale", "atom_radius", "sphere_segments", "representation",
                              "atom_radius_overrides", "element_radius_overrides",
                              "element_scales"))
    bond_shape_changed = any(previous[key] != style[key] for key in
                             ("scale", "bond_radius", "cylinder_segments", "bond_caps"))
    bond_matrices_changed = positions_changed or any(previous[key] != style[key] for key in
                            ("bond_spacing", "bond_radius", "bond_radius_overrides"))
    changed_atom_ids = set()
    if style["bond_material"] == "element" and atom_shape_changed:
        changed_atom_ids = {atom["id"] for atom in visible_atoms
                            if (_sphere_radius(previous, atom["element"]) *
                                _atom_instance_scale(previous, atom) !=
                                _sphere_radius(style, atom["element"]) *
                                _atom_instance_scale(style, atom))}
    split_bonds = {bond_key(bond["a"], bond["b"]) for bond in record["bonds"]
                   if bond["a"] in changed_atom_ids or bond["b"] in changed_atom_ids}
    update_bonds = bond_matrices_changed or bool(split_bonds)
    positions = _geometry_positions(record, style) if positions_changed or update_bonds else None
    operations = []
    if atom_shape_changed or positions_changed:
        for atom in visible_atoms:
            obj = atoms["原子_%s_%s" % (atom["element"], atom["id"])]
            fields = []
            if positions_changed:
                fields.append(("position", None, positions[atom["id"]]))
            if atom_shape_changed and _atom_instance_scale(previous, atom) != _atom_instance_scale(style, atom):
                fields.append(("scale", None, c4d.Vector(_atom_instance_scale(style, atom))))
            if fields:
                operations.append((obj, fields))
    if atom_shape_changed:
        for element in {a["element"] for a in visible_atoms}:
            fields = []
            if _sphere_radius(previous, element) != _sphere_radius(style, element):
                fields.append(("parameter", c4d.PRIM_SPHERE_RAD,
                               _sphere_radius(style, element)))
            if previous["sphere_segments"] != style["sphere_segments"]:
                fields.append(("parameter", c4d.PRIM_SPHERE_SUB,
                               style["sphere_segments"]))
            if fields:
                operations.append((prototypes["球母体_" + element], fields))
    if bond_shape_changed:
        for name, obj in prototypes.items():
            if name.startswith("键母体_"):
                operations.append((obj, [("parameter", c4d.PRIM_CYLINDER_RADIUS,
                                          style["bond_radius"] * style["scale"]),
                                         ("parameter", c4d.PRIM_CYLINDER_SEG,
                                          style["cylinder_segments"]),
                                         ("parameter", c4d.PRIM_CYLINDER_CAPS,
                                          style["bond_caps"])]))
    if update_bonds:
        expected_bonds = {}
        for name, _key, start, end, radius_scale in _bond_geometry(
                record, style, positions, visible_ids,
                None if bond_matrices_changed else split_bonds):
            expected_bonds[name] = _segment_matrix(start, end, radius_scale)
        if (set(bonds) != set(expected_bonds) if bond_matrices_changed
                else not set(expected_bonds).issubset(bonds)):
            return None
        operations.extend((bonds[name], [("matrix", None, matrix)])
                          for name, matrix in expected_bonds.items())
    return operations


def _read_live_field(obj, kind, key):
    if kind == "parameter":
        return obj[key]
    if kind == "position":
        return obj.GetRelPos()
    if kind == "scale":
        return obj.GetRelScale()
    return obj.GetMl()


def _write_live_field(obj, kind, key, value):
    if kind == "parameter":
        obj[key] = value
    elif kind == "position":
        obj.SetRelPos(value)
    elif kind == "scale":
        obj.SetRelScale(value)
    else:
        obj.SetMl(value)


def _update_live_geometry(doc, root, record, previous, style):
    """Update same-topology preview in place; return False for rebuild cases."""
    operations = _live_plan(root, record, previous, style)
    if operations is None:
        return False
    if not doc.StartUndo():
        raise RuntimeError("无法开始实时预览撤销记录")
    previous_meta = _get_meta(root)
    previous_name = root.GetName()
    changed = []
    try:
        if not doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, root):
            raise RuntimeError("无法记录分子元数据撤销")
        if previous_meta.get("record", record).get("name") != record["name"]:
            root.SetName(record["name"])
        for obj, fields in operations:
            if not doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, obj):
                raise RuntimeError("无法记录分子几何撤销")
            original = [(kind, key, _read_live_field(obj, kind, key))
                        for kind, key, _value in fields]
            changed.append((obj, original))
            for kind, key, value in fields:
                _write_live_field(obj, kind, key, value)
        _put_meta(root, {"marker": _MARKER, "schema": 1,
                         "record": record, "style": style,
                         "material_scope": previous_meta.get("material_scope"),
                         "signature_version": 2, "signature": _signature(root)})
        c4d.EventAdd()
        return True
    except Exception:
        for obj, fields in reversed(changed):
            for kind, key, value in fields:
                _write_live_field(obj, kind, key, value)
        _put_meta(root, previous_meta)
        root.SetName(previous_name)
        raise
    finally:
        doc.EndUndo()


def _update_live_private_colors(doc, root, record, previous, style, scope):
    """Recolor shared/dedicated materials without replacing their geometry."""
    if ((not style.get("inherit_materials", True) and not scope) or
            any(previous[key] != style[key] for key in style
                if key not in ("element_colors", "bond_element_colors", "bond_color"))):
        return False
    old_specs, new_specs = _material_specs(record, previous), _material_specs(record, style)
    if set(old_specs) != set(new_specs):
        return False
    materials = _prototype_materials(root)
    changes = []
    for key, new_color in new_specs.items():
        if old_specs[key] == new_color:
            continue
        mat = materials.get(key)
        if (mat is None or _material_scope(mat) != scope or
                _get_material_spec(mat) != _material_spec_key(key, old_specs[key]) or
                (scope is not None and _material_used_outside_root(doc, root, mat))):
            return False
        changes.append((mat, key, old_specs[key], new_color))
    previous_meta = _get_meta(root)
    if not doc.StartUndo():
        raise RuntimeError("无法开始预览材质撤销记录")
    changed = []
    try:
        if not doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, root):
            raise RuntimeError("无法记录分子元数据撤销")
        for mat, key, old_color, new_color in changes:
            if not doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat):
                raise RuntimeError("无法记录预览材质撤销")
            changed.append((mat, key, old_color))
            _set_material_color(mat, new_color, record_undo=False)
            _set_material_spec(mat, key, new_color, scope)
        _put_meta(root, {"marker": _MARKER, "schema": 1,
                         "record": record, "style": style,
                         "material_scope": scope,
                         "signature_version": 2, "signature": _signature(root)})
        c4d.EventAdd()
        return True
    except Exception:
        for mat, key, old_color in reversed(changed):
            _set_material_color(mat, old_color, record_undo=False)
            _set_material_spec(mat, key, old_color, scope)
        _put_meta(root, previous_meta)
        raise
    finally:
        doc.EndUndo()


def build_model(doc, record, style=None, replace_root=None):
    """Build or safely replace one selected managed model, in a single undo step.

    Call only on C4D's main thread with a document owned by the caller. Unknown
    modifications under ``replace_root`` cause a refusal instead of data loss.
    """
    if not isinstance(doc, c4d.documents.BaseDocument):
        raise ValueError("必须提供 C4D 文档")
    c4d.StopAllThreads()
    record = _normal_record(record)
    style = _normal_style(style)
    _validate_local_radius_targets(record, style)
    previous_scope = None
    if replace_root is not None:
        old = _get_meta(replace_root)
        if old is None or replace_root.GetDocument() != doc:
            raise ValueError("所选对象不是当前文档中的 SciMol 分子")
        signature_matches = old.get("signature") == _signature(replace_root)
        if not signature_matches and old.get("signature_version", 1) == 1:
            # Earlier releases used closed cylinders but did not hash caps.
            # Accept only the identical old hierarchy with every cap intact.
            signature_matches = (old.get("signature") == _signature(replace_root, include_caps=False)
                                 and all(obj[c4d.PRIM_CYLINDER_CAPS] for obj in _walk(replace_root)
                                         if obj.CheckType(c4d.Ocylinder)))
        if not signature_matches:
            raise ValueError("分子内部或材质已手工修改，请生成新模型以保留修改")
        previous_scope = old.get("material_scope")
        if all(old["record"].get(key) == record.get(key) for key in
               ("atoms", "bonds", "smiles", "structure_key")):
            previous_style = _normal_style(old["style"])
            if previous_style == style and old["record"] == record:
                return replace_root
            if _update_live_geometry(doc, replace_root, record, previous_style, style):
                return replace_root
            if _update_live_private_colors(doc, replace_root, record,
                                           previous_style, style, previous_scope):
                return replace_root
    if style.get("inherit_materials", True):
        material_scope = None
    elif (replace_root is not None and previous_scope and
          not _normal_style(old["style"]).get("inherit_materials", True)):
        material_scope = previous_scope
    else:
        material_scope = uuid.uuid4().hex
    material_specs = _material_specs(record, style)
    reusable = _reusable_materials(doc, material_specs, material_scope)
    recolor = []
    if (replace_root is not None and material_scope is not None and
            material_scope == previous_scope):
        for key, mat in _prototype_materials(replace_root).items():
            if key in material_specs and key not in reusable and (
                    _material_scope(mat) == material_scope and
                    _get_material_spec(mat) is not None and
                    not _material_used_outside_root(doc, replace_root, mat)):
                recolor.append((mat, key, material_specs[key],
                                _get_material_spec(mat)[2]))
                reusable[key] = mat
    if not doc.StartUndo():
        raise RuntimeError("无法开始撤销记录")
    made_materials = []
    changed_materials = []
    new_root = None
    inserted = False
    committed = False
    removed_children = []
    added_children = []
    previous_meta = _get_meta(replace_root) if replace_root is not None else None
    try:
        mats = {}
        for key, color in material_specs.items():
            if key in reusable:
                mats[key] = reusable[key]
                continue
            name = ("球_" if key[0] == "atom" else "键_") + key[1]
            mat = _node_material(doc, name, color)
            made_materials.append(mat)
            _set_material_spec(mat, key, color, material_scope)
            mats[key] = mat
        for mat, key, color, old_color in recolor:
            if not doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat):
                raise RuntimeError("无法记录预览材质撤销")
            changed_materials.append((mat, key, old_color))
            _set_material_color(mat, color, record_undo=False)
            _set_material_spec(mat, key, color, material_scope)
        new_root = _make_hierarchy(record, style, mats)
        if replace_root is None:
            _put_meta(new_root, {"marker": _MARKER, "schema": 1,
                                 "record": record, "style": style,
                                 "material_scope": material_scope,
                                 "signature_version": 2,
                                 "signature": _signature(new_root)})
            doc.InsertObject(new_root)
            inserted = True
            if not doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, new_root):
                raise RuntimeError("无法记录对象撤销")
            result = new_root
        else:
            # Preserve the root itself: its parent, transform, user data, tags,
            # tracks and external links remain valid across a style update.
            # Only the existing metadata value changes on the root. Its child
            # groups have their own delete/create undo items below; recording
            # the hierarchy twice breaks redo and replaces the root wrapper.
            if not doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, replace_root):
                raise RuntimeError("无法记录分子元数据撤销")
            # An explicit panel rename changes the scene root too. Style-only
            # updates keep a name the user set directly in Object Manager.
            if old["record"]["name"] != record["name"]:
                replace_root.SetName(record["name"])
            old_children = []
            child = replace_root.GetDown()
            while child:
                old_children.append(child)
                child = child.GetNext()
            for child in old_children:
                if not doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, child):
                    raise RuntimeError("无法记录旧几何撤销")
                child.Remove()
                removed_children.append(child)
            while new_root.GetDown():
                child = new_root.GetDown()
                child.Remove()
                child.InsertUnderLast(replace_root)
                added_children.append(child)
                if not doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, child):
                    raise RuntimeError("无法记录新几何撤销")
            _put_meta(replace_root, {"marker": _MARKER, "schema": 1,
                                     "record": record, "style": style,
                                     "material_scope": material_scope,
                                     "signature_version": 2,
                                     "signature": _signature(replace_root)})
            result = replace_root
        # C4D records selection changes too. Keep selection in this undo list
        # so a single Ctrl+Z reverses the generation/update itself.
        if doc.GetActiveObject() != result:
            doc.SetActiveObject(result, c4d.SELECTION_NEW)
        committed = True
        c4d.EventAdd()
        return result
    except Exception:
        if replace_root is not None and not committed:
            for child in reversed(added_children):
                child.Remove()
            for child in removed_children:
                child.InsertUnderLast(replace_root)
            if previous_meta is not None:
                _put_meta(replace_root, previous_meta)
        if not committed and inserted and new_root is not None:
            new_root.Remove()
        if not committed:
            for mat, key, color in reversed(changed_materials):
                _set_material_color(mat, color, record_undo=False)
                _set_material_spec(mat, key, color, material_scope)
            for mat in reversed(made_materials):
                if mat.GetDocument() == doc:
                    mat.Remove()
        raise
    finally:
        doc.EndUndo()
