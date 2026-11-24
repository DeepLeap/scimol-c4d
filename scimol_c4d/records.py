"""Validate portable molecule records without importing C4D or RDKit."""

import copy
import hashlib
import json
import math

MAX_ATOMS = 300
DEPICTION_VERSION = 2
PREVIEW_FIELDS = ("thumbnail", "themed_thumbnail", "transparent_thumbnail",
                  "transparent_dark_thumbnail", "thumbnail_atom_positions",
                  "thumbnail_size", "depiction_version")
DEFAULT_STYLE = {
    "scale": 50.0, "atom_radius": 0.30, "bond_radius": 0.08,
    "bond_spacing": 0.18, "bond_mode": "multiple",
    "bond_material": "element", "show_hydrogens": True,
    "quality": 24, "bond_color": [0.65, 0.65, 0.65],
    "sphere_segments": 24, "cylinder_segments": 24,
    "element_colors": {}, "bond_element_colors": {},
    "atom_radius_overrides": {}, "element_radius_overrides": {},
    "element_scales": {},
    "bond_radius_overrides": {},
    "position_overrides": {},
    "plane_groups": {}, "representation": "ball_stick", "ball_stick_radius": 0.30,
    "bond_caps": True, "orientation": "auto", "center_atom_ids": [],
    "inherit_materials": True,
}


def record_integrity(record):
    """Bind cached geometry to its molecular graph; names/styles may change."""
    payload = {key: record.get(key) for key in (
        "schema_version", "smiles", "structure_key", "atoms", "bonds",
        "molblock", "has_3d", "stereo_status", "coordinates_ready",
    )}
    payload["graph_molblock"] = record.get("graph_molblock", record.get("molblock"))
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def validate_record(record, require_3d=False):
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("不支持的结构记录版本")
    result = copy.deepcopy(record)
    atoms, bonds = result.get("atoms"), result.get("bonds")
    if not isinstance(atoms, list) or not 1 <= len(atoms) <= MAX_ATOMS:
        raise ValueError("结构必须包含 1–300 个原子（含氢）")
    if not isinstance(bonds, list) or len(bonds) > MAX_ATOMS * 4:
        raise ValueError("化学键列表无效或超出范围")
    for index, atom in enumerate(atoms):
        if not isinstance(atom, dict) or atom.get("id") != index:
            raise ValueError("原子编号不连续")
        element = atom.get("element", "")
        if not isinstance(element, str) or not element.isalpha() or len(element) > 2:
            raise ValueError("原子元素无效")
        for axis in ("x", "y", "z"):
            value = atom.get(axis)
            if not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError("原子坐标无效")
        if not isinstance(atom.get("charge", 0), int) or not isinstance(atom.get("isotope", 0), int):
            raise ValueError("原子电荷或同位素无效")
    seen = set()
    for bond in bonds:
        if not isinstance(bond, dict):
            raise ValueError("化学键记录无效")
        a, b = bond.get("a"), bond.get("b")
        if not isinstance(a, int) or not isinstance(b, int) or a == b:
            raise ValueError("化学键端点无效")
        if not (0 <= a < len(atoms) and 0 <= b < len(atoms)):
            raise ValueError("化学键引用了不存在的原子")
        key = tuple(sorted((a, b)))
        if key in seen:
            raise ValueError("存在重复化学键")
        seen.add(key)
        if bond.get("order") not in (1, 1.0, 1.5, 2, 2.0, 3, 3.0):
            raise ValueError("首版不支持这种化学键")
    if not isinstance(result.get("smiles"), str) or not result["smiles"]:
        raise ValueError("结构缺少 SMILES")
    if not isinstance(result.get("name"), str) or len(result["name"]) > 300:
        raise ValueError("结构名称无效")
    if require_3d and not result.get("has_3d"):
        raise ValueError("该结构还没有三维坐标")
    expected = hashlib.sha256(result["smiles"].encode("utf-8")).hexdigest()
    if result.get("structure_key") != expected:
        raise ValueError("结构身份校验失败")
    if result.get("record_integrity") and result["record_integrity"] != record_integrity(result):
        raise ValueError("结构坐标或化学键数据已损坏，请重新导入原结构")
    if result.get("coordinates_ready") and not result.get("record_integrity"):
        result["coordinates_ready"] = False
    return result


def normalized_style(style=None):
    result = copy.deepcopy(DEFAULT_STYLE)
    if style:
        if not isinstance(style, dict) or set(style) - set(DEFAULT_STYLE):
            raise ValueError("显示参数包含未知字段")
        result.update(style)
    for key in ("scale", "atom_radius", "bond_radius", "bond_spacing"):
        value = result[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("尺寸参数必须为正数")
    if result["bond_mode"] not in ("single", "multiple"):
        raise ValueError("键显示模式无效")
    if result["bond_material"] not in ("uniform", "element"):
        raise ValueError("键材质模式无效")
    if result["quality"] not in (12, 24, 36):
        raise ValueError("几何精度无效")
    for key in ("sphere_segments", "cylinder_segments"):
        if style and key not in style:
            result[key] = result["quality"]
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 3 <= value <= 512:
            raise ValueError("分段必须是 3–512 的整数")
    if result["representation"] not in ("ball_stick", "space_fill", "continuous"):
        raise ValueError("模型显示类型无效")
    if not isinstance(result["bond_caps"], bool):
        raise ValueError("键封顶设置无效")
    if not isinstance(result["inherit_materials"], bool):
        raise ValueError("材质继承设置无效")
    if result["orientation"] not in ("original", "auto", "xy", "xz", "yz"):
        raise ValueError("整体朝向无效")
    centers = result["center_atom_ids"]
    if (not isinstance(centers, list) or len(centers) > MAX_ATOMS or
            any(isinstance(item, bool) or not isinstance(item, int) or
                not 0 <= item < MAX_ATOMS for item in centers)):
        raise ValueError("中心原子列表无效")
    result["center_atom_ids"] = sorted(set(centers))
    if not isinstance(result["ball_stick_radius"], (int, float)) or not math.isfinite(result["ball_stick_radius"]) or result["ball_stick_radius"] <= 0:
        raise ValueError("球棍半径预设无效")
    if not isinstance(result["element_colors"], dict) or not isinstance(result["bond_element_colors"], dict):
        raise ValueError("元素颜色配置无效")
    colors = [result["bond_color"]] + list(result["element_colors"].values()) + list(result["bond_element_colors"].values())
    for color in colors:
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            raise ValueError("颜色必须为 RGB 三元组")
        if any(not isinstance(c, (int, float)) or not math.isfinite(c) or not 0 <= c <= 1 for c in color):
            raise ValueError("RGB 颜色必须在 0–1 范围内")
    result["position_overrides"] = normalized_position_overrides(result["position_overrides"])
    result["plane_groups"] = normalized_plane_groups(result["plane_groups"])
    result["atom_radius_overrides"] = normalized_atom_radius_overrides(
        result["atom_radius_overrides"])
    result["element_radius_overrides"] = normalized_element_radius_overrides(
        result["element_radius_overrides"])
    result["element_scales"] = normalized_element_scales(result["element_scales"])
    result["bond_radius_overrides"] = normalized_bond_radius_overrides(
        result["bond_radius_overrides"])
    return result


def _radius(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value <= 0):
        raise ValueError("局部半径必须是有限正数")
    return float(value)


def _atom_id(value):
    if (not isinstance(value, int) or isinstance(value, bool) or
            not 0 <= value < MAX_ATOMS):
        raise ValueError("局部原子编号无效")
    return value


def bond_key(a, b):
    """Canonical identity for one chemical bond, regardless of endpoint order."""
    first, second = sorted((_atom_id(a), _atom_id(b)))
    if first == second:
        raise ValueError("化学键不能连接同一原子")
    return "%d:%d" % (first, second)


def normalized_atom_radius_overrides(value):
    if not isinstance(value, dict) or len(value) > MAX_ATOMS:
        raise ValueError("局部原子半径配置无效")
    result = {}
    for key, radius in value.items():
        if (not isinstance(key, str) or not key.isdigit() or
                str(int(key)) != key):
            raise ValueError("局部原子编号无效")
        atom_id = _atom_id(int(key))
        result[str(atom_id)] = _radius(radius)
    return result


_ELEMENT_SYMBOLS = frozenset((
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La "
    "Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi "
    "Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt "
    "Ds Rg Cn Nh Fl Mc Lv Ts Og").split())

_ATOM_RADIUS_FACTOR = {
    "H": 0.60, "C": 1.0, "N": 0.94, "O": 0.90,
    "S": 1.13, "P": 1.10, "F": 0.88, "Cl": 1.08,
    "Br": 1.18, "I": 1.30,
}
_VDW_RADII = {"H": 1.2, "C": 1.7, "N": 1.6, "O": 1.55, "S": 1.8,
              "P": 1.95, "F": 1.5, "Cl": 1.8, "Br": 1.9, "I": 2.1}


def atom_display_factor(style, element, radius=None):
    """Representation factor shared by rendering and legacy-style migration."""
    ball = _ATOM_RADIUS_FACTOR.get(element, 1.0)
    fill = _VDW_RADII.get(element, 2.0)
    if style["representation"] == "ball_stick":
        return ball
    if style["representation"] == "space_fill":
        return fill
    if radius is None:
        radius = style["atom_radius"]
    blend = max(0.0, min(1.0, (radius - 0.30) / 0.70))
    return ball + blend * (fill - ball)


def normalized_element_radius_overrides(value):
    if not isinstance(value, dict) or len(value) > len(_ELEMENT_SYMBOLS):
        raise ValueError("元素半径配置无效")
    result = {}
    for symbol, radius in value.items():
        if not isinstance(symbol, str) or symbol not in _ELEMENT_SYMBOLS:
            raise ValueError("元素半径的元素符号无效")
        result[symbol] = _radius(radius)
    return result


def normalized_element_scales(value):
    """Validate positive finite relative element sizes; unity needs no key."""
    if not isinstance(value, dict) or len(value) > len(_ELEMENT_SYMBOLS):
        raise ValueError("元素缩放配置无效")
    result = {}
    for symbol, scale in value.items():
        if not isinstance(symbol, str) or symbol not in _ELEMENT_SYMBOLS:
            raise ValueError("元素缩放的元素符号无效")
        if (isinstance(scale, bool) or not isinstance(scale, (int, float)) or
                not math.isfinite(scale) or scale <= 0):
            raise ValueError("元素缩放倍率必须是有限正数")
        if scale != 1:
            result[symbol] = float(scale)
    return result


def migrate_element_scales(style):
    """Convert old absolute element radii to equivalent final-radius multipliers.

    The returned normalized copy has no legacy overrides. Existing new-scale
    keys for elements without a legacy radius are retained. The conversion is
    exact for the current representation and overall atom radius; subsequent
    atom-radius changes make migrated elements follow the overall control.
    """
    result = normalized_style(style)
    if not result["element_radius_overrides"]:
        return result
    scales = dict(result["element_scales"])
    global_radius = result["atom_radius"]
    for symbol, legacy_radius in result["element_radius_overrides"].items():
        legacy_final = legacy_radius * atom_display_factor(result, symbol, legacy_radius)
        base_final = global_radius * atom_display_factor(result, symbol, global_radius)
        scale = legacy_final / base_final
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("旧元素半径无法转换为有限缩放倍率")
        if scale == 1:
            scales.pop(symbol, None)
        else:
            scales[symbol] = scale
    result["element_scales"] = scales
    result["element_radius_overrides"] = {}
    return result


def normalized_bond_radius_overrides(value):
    if not isinstance(value, dict) or len(value) > MAX_ATOMS * 4:
        raise ValueError("局部化学键半径配置无效")
    result = {}
    for key, radius in value.items():
        if not isinstance(key, str) or key.count(":") != 1:
            raise ValueError("局部化学键编号无效")
        first, second = key.split(":")
        if not first.isdigit() or not second.isdigit():
            raise ValueError("局部化学键编号无效")
        canonical = bond_key(int(first), int(second))
        if canonical != key:
            raise ValueError("局部化学键编号必须按较小原子号在前")
        result[canonical] = _radius(radius)
    return result


def normalized_position_overrides(value):
    if not isinstance(value, dict) or len(value) > MAX_ATOMS:
        raise ValueError("显示坐标覆盖无效")
    result = {}
    for key, xyz in value.items():
        label = str(key)
        if not label.isdigit() or str(int(label)) != label or not 0 <= int(label) < MAX_ATOMS:
            raise ValueError("显示坐标的原子编号无效")
        if not isinstance(xyz, (list, tuple)) or len(xyz) != 3:
            raise ValueError("显示坐标必须为三元组")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in xyz):
            raise ValueError("显示坐标必须有限")
        result[label] = [float(v) for v in xyz]
    return result


def normalized_plane_groups(value):
    if not isinstance(value, dict) or len(value) > MAX_ATOMS:
        raise ValueError("平面组配置无效")
    result, assigned = {}, set()
    for key, group in value.items():
        label = str(key)
        if not label.isdigit() or str(int(label)) != label or int(label) < 1 or not isinstance(group, dict):
            raise ValueError("平面组编号无效")
        ids = group.get("atom_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < MAX_ATOMS for i in ids):
            raise ValueError("平面组原子列表无效")
        if len(ids) != len(set(ids)) or assigned.intersection(ids):
            raise ValueError("同一个重原子只能属于一个平面组")
        assigned.update(ids)
        origin = normalized_position_overrides({"0": group.get("origin")})["0"]
        normal = normalized_position_overrides({"0": group.get("normal")})["0"]
        length = math.hypot(*normal)
        if not math.isfinite(length) or length < 1e-9:
            raise ValueError("平面方向无效")
        color = group.get("color", [.25, .6, .9])
        if not isinstance(color, (list, tuple)) or len(color) != 3 or any(not isinstance(c, (int, float)) or not math.isfinite(c) or not 0 <= c <= 1 for c in color):
            raise ValueError("平面色框颜色无效")
        result[label] = {"atom_ids": sorted(ids), "origin": origin,
                         "normal": [v/length for v in normal], "color": list(color)}
    return result


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
