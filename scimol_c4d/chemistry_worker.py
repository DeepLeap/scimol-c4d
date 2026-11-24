"""Isolated RDKit worker. One JSON request on stdin, one JSON response on stdout.

This module never imports Cinema 4D. Diagnostics from RDKit and uncaught errors go
to stderr; stdout is reserved for the response consumed by the C4D plugin.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from scimol_c4d.records import record_integrity, DEPICTION_VERSION
from scimol_c4d import resolve_cache
from scimol_c4d.search_index import (
    BUILTIN_NAMES,
    LOCAL_STRUCTURES,
    is_valid_formula,
    normalize_query_text,
    rank_local_names,
    suggest_names,
)

from rdkit import Chem, RDLogger, rdBase
from rdkit.Chem import AllChem, Draw, rdMolDescriptors, rdDepictor


RDLogger.DisableLog("rdApp.warning")
MAX_ATOMS = 300
MAX_CANDIDATES = 9
FORMULA_SCAN_LIMIT = 30
MAX_INPUT_BYTES = 8 * 1024 * 1024
THUMBNAIL_SIZE = (360, 280)
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
CHINESE_NAMES = LOCAL_STRUCTURES
FORMULA_PATTERN = re.compile(r"(?:[A-Z][a-z]?\d*){1,15}$")


class ChemistryError(ValueError):
    pass


def _network(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SciMol-C4D/0.1 (educational structure lookup)"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = response.read(MAX_INPUT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ChemistryError("未找到匹配结构，请换用英文名、SMILES 或文件") from exc
        raise ChemistryError(f"结构服务返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ChemistryError("结构服务暂不可用，请检查网络或改用 SMILES、文件") from exc
    if len(data) > MAX_INPUT_BYTES:
        raise ChemistryError("结构服务结果过大")
    return data


def _connected_molecule(mol: Chem.Mol) -> None:
    if mol is None or mol.GetNumAtoms() == 0:
        raise ChemistryError("无法识别有效分子结构")
    if len(Chem.GetMolFrags(mol)) != 1:
        raise ChemistryError("当前只支持单个共价连接的分子；请拆分盐、混合物或多个组分")
    if any(atom.GetAtomicNum() == 0 or atom.HasQuery() for atom in mol.GetAtoms()):
        raise ChemistryError("当前不支持可变基团、查询原子或缩写结构")
    if any(bond.HasQuery() or bond.GetBondTypeAsDouble() not in (1.0, 1.5, 2.0, 3.0) for bond in mol.GetBonds()):
        raise ChemistryError("当前不支持查询键或特殊键")
    with_h = Chem.AddHs(mol, addCoords=False)
    if with_h.GetNumAtoms() > MAX_ATOMS:
        raise ChemistryError(f"分子超过 {MAX_ATOMS} 个原子（含氢）的上限")


def _stereo(mol: Chem.Mol) -> tuple[str, list[str]]:
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    found = Chem.FindPotentialStereo(mol)
    if not found:
        return "none", []
    unknown = any(str(item.specified) == "Unspecified" for item in found)
    if unknown:
        return "unspecified", ["结构含未指定的立体中心或双键构型；生成的三维方向仅为一种构象"]
    return "specified", []


def _coordinates(mol: Chem.Mol) -> tuple[bool, list[tuple[float, float, float]]]:
    if not mol.GetNumConformers():
        return False, [(0.0, 0.0, 0.0) for _ in mol.GetAtoms()]
    conf = mol.GetConformer()
    xyz = [tuple(float(v) for v in conf.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
    has_3d = bool(conf.Is3D()) and any(abs(p[2]) > 1e-4 for p in xyz)
    # Planar 3D molecules are possible. Is3D is authoritative when the coordinates
    # span x/y even if all z values happen to be zero.
    if conf.Is3D() and not has_3d and mol.GetNumAtoms() > 1:
        has_3d = any(math.dist(xyz[0], point) > 1e-4 for point in xyz[1:])
    return has_3d, xyz


def _straighten_depiction(mol: Chem.Mol) -> None:
    """Rotate only the depiction copy; prefer a benzene/six-membered ring."""
    rdDepictor.StraightenDepiction(mol, minimizeRotation=True)
    rings = list(mol.GetRingInfo().AtomRings())
    if not rings:
        return
    def priority(ring):
        benzene = len(ring) == 6 and all(mol.GetAtomWithIdx(i).GetAtomicNum() == 6 and
                                       mol.GetAtomWithIdx(i).GetIsAromatic() for i in ring)
        return (0 if benzene else 1 if len(ring) == 6 else 2, len(ring), tuple(sorted(ring)))
    ring = min(rings, key=priority)
    conf = mol.GetConformer()
    angles = []
    for index, first in enumerate(ring):
        a = conf.GetAtomPosition(first)
        b = conf.GetAtomPosition(ring[(index+1) % len(ring)])
        angle = math.atan2(b.y-a.y, b.x-a.x)
        angles.append((angle+math.pi/2) % math.pi-math.pi/2)
    angle = min(angles, key=abs)
    cosine, sine = math.cos(angle), math.sin(angle)
    for index in range(mol.GetNumAtoms()):
        p = conf.GetAtomPosition(index)
        conf.SetAtomPosition(index, (cosine*p.x+sine*p.y, -sine*p.x+cosine*p.y, p.z))


def _thumbnail(mol: Chem.Mol, cache_dir: Path, key: str) -> tuple[str, str, str, str, dict[str, list[float]]]:
    # Keep the source indices on atoms before RemoveHs, since removing an
    # explicit hydrogen can renumber the remaining heavy atoms.
    source = Chem.Mol(mol)
    for atom in source.GetAtoms():
        atom.SetIntProp("_thumbnail_original_id", atom.GetIdx())
    clean = Chem.RemoveHs(source)
    AllChem.Compute2DCoords(clean)
    _straighten_depiction(clean)
    drawer = Draw.rdMolDraw2D.MolDraw2DCairo(*THUMBNAIL_SIZE)
    drawer.DrawMolecule(clean)
    drawer.FinishDrawing()
    positions = {}
    for atom in clean.GetAtoms():
        if atom.GetAtomicNum() != 1:
            point = drawer.GetDrawCoords(atom.GetIdx())
            positions[str(atom.GetIntProp("_thumbnail_original_id"))] = [float(point.x), float(point.y)]
    # The structure key describes chemical identity, not atom order. Include
    # the exact depiction input so reordered records cannot reuse one PNG.
    depiction = str(DEPICTION_VERSION).encode("ascii") + Chem.MolToMolBlock(clean).encode("utf-8")
    suffix = hashlib.sha256(depiction).hexdigest()[:20]
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = (cache_dir / f"{key}-{suffix}.png").resolve()
    if not path.exists():
        path.write_bytes(drawer.GetDrawingText())
    themed_path = (cache_dir / f"{key}-{suffix}-dark-v1.png").resolve()
    if not themed_path.exists():
        themed = Draw.rdMolDraw2D.MolDraw2DCairo(*THUMBNAIL_SIZE)
        options = themed.drawOptions()
        options.setBackgroundColour((0.18, 0.19, 0.21, 1.0))
        palette = options.getAtomPalette()
        light = (0.84, 0.86, 0.89, 1.0)
        for atomic_number in (-1, 0, 1, 6):
            palette[atomic_number] = light
        options.setAtomPalette(palette)
        options.setAnnotationColour(light)
        options.setBondNoteColour(light)
        themed.DrawMolecule(clean)
        themed.FinishDrawing()
        themed_path.write_bytes(themed.GetDrawingText())
    transparent_paths = []
    for variant, carbon in (("light", (0.88, 0.90, 0.93, 1.0)),
                            ("dark", (0.08, 0.09, 0.11, 1.0))):
        overlay_path = (cache_dir / f"{key}-{suffix}-{variant}-transparent-v1.png").resolve()
        if not overlay_path.exists():
            overlay = Draw.rdMolDraw2D.MolDraw2DCairo(*THUMBNAIL_SIZE)
            overlay_options = overlay.drawOptions()
            overlay_options.clearBackground = False
            overlay_palette = overlay_options.getAtomPalette()
            for atomic_number in (-1, 0, 1, 6):
                overlay_palette[atomic_number] = carbon
            overlay_options.setAtomPalette(overlay_palette)
            overlay_options.setAnnotationColour(carbon)
            overlay_options.setBondNoteColour(carbon)
            overlay.DrawMolecule(clean)
            overlay.FinishDrawing()
            overlay_path.write_bytes(overlay.GetDrawingText())
        transparent_paths.append(str(overlay_path))
    return str(path), str(themed_path), *transparent_paths, positions


def _check_record_atom_order(record: dict, mol: Chem.Mol) -> None:
    atoms = record.get("atoms")
    if not isinstance(atoms, list) or len(atoms) < mol.GetNumAtoms():
        raise ChemistryError("结构记录原子编号与 MolBlock 不一致")
    for index, atom in enumerate(mol.GetAtoms()):
        entry = atoms[index]
        if (not isinstance(entry, dict) or entry.get("id") != index
                or entry.get("element") != atom.GetSymbol()
                or entry.get("charge") != atom.GetFormalCharge()
                or entry.get("isotope") != atom.GetIsotope()):
            raise ChemistryError("结构记录原子编号与 MolBlock 不一致")


def _check_graph_atom_order(graph: Chem.Mol, coords: Chem.Mol) -> None:
    if graph.GetNumAtoms() > coords.GetNumAtoms():
        raise ChemistryError("原始图与三维记录的原子编号不一致")
    for index, atom in enumerate(graph.GetAtoms()):
        other = coords.GetAtomWithIdx(index)
        if (atom.GetAtomicNum(), atom.GetFormalCharge(), atom.GetIsotope()) != (
                other.GetAtomicNum(), other.GetFormalCharge(), other.GetIsotope()):
            raise ChemistryError("原始图与三维记录的原子编号不一致")
    graph_edges = {(min(b.GetBeginAtomIdx(), b.GetEndAtomIdx()),
                    max(b.GetBeginAtomIdx(), b.GetEndAtomIdx()), b.GetBondTypeAsDouble())
                   for b in graph.GetBonds()}
    coord_edges = {(min(b.GetBeginAtomIdx(), b.GetEndAtomIdx()),
                    max(b.GetBeginAtomIdx(), b.GetEndAtomIdx()), b.GetBondTypeAsDouble())
                   for b in coords.GetBonds()
                   if b.GetBeginAtomIdx() < graph.GetNumAtoms()
                   and b.GetEndAtomIdx() < graph.GetNumAtoms()}
    if graph_edges != coord_edges:
        raise ChemistryError("原始图与三维记录的原子编号不一致")


def _record(mol: Chem.Mol, *, name: str, source: dict, cache_dir: Path,
            warnings: list[str] | None = None) -> dict:
    _connected_molecule(mol)
    mol = Chem.Mol(mol)
    stereo_status, stereo_warnings = _stereo(mol)
    smiles = Chem.MolToSmiles(Chem.RemoveHs(Chem.Mol(mol)), isomericSmiles=True)
    key = hashlib.sha256(smiles.encode("utf-8")).hexdigest()
    has_3d, xyz = _coordinates(mol)
    atoms = []
    for i, atom in enumerate(mol.GetAtoms()):
        x, y, z = xyz[i]
        atoms.append({"id": i, "element": atom.GetSymbol(), "x": x, "y": y,
                      "z": z, "charge": atom.GetFormalCharge(), "isotope": atom.GetIsotope()})
    # Geometry needs drawable 1/2 bonds in aromatic rings, while the aromatic
    # flag preserves the chemically normalized interpretation for UI/export.
    drawable = Chem.Mol(mol)
    Chem.Kekulize(drawable, clearAromaticFlags=False)
    bonds = [{"a": bond.GetBeginAtomIdx(), "b": bond.GetEndAtomIdx(),
              "order": bond.GetBondTypeAsDouble(), "aromatic": bond.GetIsAromatic()}
             for bond in drawable.GetBonds()]
    thumbnail, themed_thumbnail, preview_light, preview_dark, positions = _thumbnail(mol, cache_dir, key)
    record = {
        "schema_version": 1, "name": name, "formula": rdMolDescriptors.CalcMolFormula(mol),
        "smiles": smiles, "structure_key": key, "source": source,
        "stereo_status": stereo_status, "warnings": list(warnings or []) + stereo_warnings,
        "atoms": atoms, "bonds": bonds, "has_3d": has_3d,
        "coordinates_ready": False,
        "thumbnail": thumbnail,
        "themed_thumbnail": themed_thumbnail,
        "transparent_thumbnail": preview_dark,
        "transparent_dark_thumbnail": preview_light,
        "thumbnail_atom_positions": positions,
        "thumbnail_size": list(THUMBNAIL_SIZE),
        "depiction_version": DEPICTION_VERSION,
        "molblock": Chem.MolToMolBlock(mol),
    }
    record["record_integrity"] = record_integrity(record)
    return record


def _from_smiles(text: str, name: str, source: dict, cache_dir: Path) -> dict:
    mol = Chem.MolFromSmiles(text)
    if mol is None:
        raise ChemistryError("SMILES 无法解析；请检查原子、括号和键的写法")
    return _record(mol, name=name, source=source, cache_dir=cache_dir)


def _parse_cdxml(path: Path) -> None:
    # ElementTree does not fetch the external ChemDraw DTD. Check unsupported
    # features before RDKit's deliberately partial CDXML reader sees the file.
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ChemistryError("CDXML 文件格式错误") from exc
    for node in tree.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        attrs = node.attrib
        if tag == "n":
            if attrs.get("NodeType", "Element") != "Element":
                raise ChemistryError("CDXML 含缩写、可变基团或特殊节点，当前无法安全导入")
            if any(x in attrs for x in ("AtomList", "GenericNickname", "Nickname", "Query", "Rgroup")):
                raise ChemistryError("CDXML 含查询原子或可变基团，当前无法安全导入")
        elif tag == "b":
            if attrs.get("Order", "1") not in ("1", "2", "3", "1.5"):
                raise ChemistryError("CDXML 含不支持的特殊键")
            if any(x in attrs for x in ("Query", "BondType")):
                raise ChemistryError("CDXML 含查询键或特殊键")


def _from_file(path_text: str, cache_dir: Path) -> list[dict]:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ChemistryError("文件不存在或超过 8 MB 上限")
    ext = path.suffix.lower()
    if ext not in (".mol", ".sdf", ".cdxml"):
        raise ChemistryError("首版仅支持 CDXML、MOL、SDF 文件")
    source = {"kind": "file", "path": str(path), "format": ext[1:]}
    data = path.read_bytes()
    if ext == ".mol":
        mols = [Chem.MolFromMolBlock(data.decode("utf-8-sig"), sanitize=True, removeHs=False)]
    elif ext == ".sdf":
        mols = list(Chem.ForwardSDMolSupplier(io.BytesIO(data), sanitize=True, removeHs=False))
        # RDKit may omit malformed trailing SD records entirely. Count input
        # delimiters so a broken entry never disappears without an error.
        expected = data.count(b"$$$$")
        if expected and expected != len(mols):
            raise ChemistryError("SDF 文件包含无法解析的结构；未跳过任何条目")
    else:
        _parse_cdxml(path)
        mols = list(Chem.MolsFromCDXML(data.decode("utf-8-sig"), sanitize=True, removeHs=False))
    if not mols or any(mol is None for mol in mols):
        raise ChemistryError("文件包含无法解析的结构；未跳过任何条目")
    if len(mols) > MAX_CANDIDATES:
        raise ChemistryError("文件内结构超过 9 个；请先拆分文件")
    records = []
    for index, mol in enumerate(mols, start=1):
        label = mol.GetProp("_Name").strip() if mol.HasProp("_Name") else ""
        name = label or (path.stem if len(mols) == 1 else f"{path.stem} · 结构 {index}")
        records.append(_record(mol, name=name, source={**source, "item": index}, cache_dir=cache_dir))
    return records


def _pubchem_cids(kind: str, text: str) -> list[int]:
    encoded = urllib.parse.quote(text, safe="")
    if kind == "formula":
        if not is_valid_formula(text):
            raise ChemistryError("分子式格式不正确；请按 C2H6O 形式输入")
        url = f"{PUBCHEM}/fastformula/{encoded}/cids/JSON?MaxRecords={FORMULA_SCAN_LIMIT}&AllowOtherElements=false"
    else:
        url = f"{PUBCHEM}/name/{encoded}/cids/JSON"
    payload = json.loads(_network(url).decode("utf-8"))
    cids = payload.get("IdentifierList", {}).get("CID", [])
    if not cids:
        raise ChemistryError("没有匹配的已收录结构")
    return [int(cid) for cid in cids[:FORMULA_SCAN_LIMIT if kind == "formula" else MAX_CANDIDATES]]


def _pubchem_names(cids: list[int]) -> dict[int, str]:
    joined = ",".join(str(cid) for cid in cids)
    try:
        payload = json.loads(_network(f"{PUBCHEM}/cid/{joined}/property/IUPACName/JSON").decode("utf-8"))
    except (ChemistryError, ValueError):
        return {}
    return {int(item["CID"]): str(item["IUPACName"])
            for item in payload.get("PropertyTable", {}).get("Properties", [])
            if item.get("CID") and item.get("IUPACName")}


def _pubchem_records(cids: list[int], names: dict[int, str],
                     cache_dir: Path, *, query: str, kind: str) -> list[dict]:
    joined = ",".join(str(cid) for cid in cids)
    sdf = _network(f"{PUBCHEM}/cid/{joined}/SDF?record_type=2d")
    parsed = list(Chem.ForwardSDMolSupplier(io.BytesIO(sdf), sanitize=True, removeHs=False))
    if len(parsed) != len(cids) or any(mol is None for mol in parsed):
        raise ChemistryError("数据库候选结构下载不完整；请重试")
    by_cid = {}
    for mol in parsed:
        try:
            cid = int(mol.GetProp("_Name"))
        except (ValueError, KeyError) as exc:
            raise ChemistryError("数据库候选结构缺少 CID 标识") from exc
        if cid in by_cid:
            raise ChemistryError("数据库返回了重复结构标识")
        by_cid[cid] = mol
    if set(by_cid) != set(cids):
        raise ChemistryError("数据库候选结构与标识不匹配")
    # PubChem's 2D SDF normally includes this property. Only ask the property
    # endpoint for CID entries whose SDF label is absent.
    missing_names = []
    for cid in cids:
        label = by_cid[cid].GetProp("PUBCHEM_IUPAC_NAME").strip() if by_cid[cid].HasProp("PUBCHEM_IUPAC_NAME") else ""
        if label:
            names[cid] = label
        elif cid not in names:
            missing_names.append(cid)
    if missing_names:
        names.update(_pubchem_names(missing_names))
    records = []
    seen_keys = set()
    for cid in cids:
        if kind == "formula":
            candidate = by_cid[cid]
            if any(atom.GetIsotope() for atom in candidate.GetAtoms()) or len(Chem.GetMolFrags(candidate)) != 1:
                continue
        warnings = ["分子式搜索仅检查前 30 个数据库结果，默认过滤同位素及多组分结构，最多显示 9 个，不保证穷尽异构体"] if kind == "formula" else []
        candidate_record = _record(by_cid[cid], name=names.get(cid) or f"PubChem CID {cid}",
                                   source={"kind": "pubchem", "cid": cid, "query": query,
                                           "name": names.get(cid) or f"CID {cid}",
                                           "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"},
                                   cache_dir=cache_dir, warnings=warnings)
        if candidate_record["structure_key"] in seen_keys:
            continue
        seen_keys.add(candidate_record["structure_key"])
        records.append(candidate_record)
        if len(records) == MAX_CANDIDATES:
            break
    if not records:
        raise ChemistryError("前 30 个数据库结果中没有普通结构；可改用名称、SMILES 或文件")
    return records


def _resolve(request: dict, cache_dir: Path) -> list[dict]:
    kind = request.get("kind")
    if kind == "file":
        return _from_file(str(request.get("path", "")), cache_dir)
    text = normalize_query_text(request.get("text", ""))
    if not text or len(text) > 512:
        raise ChemistryError("请输入 1–512 个字符的名称、分子式或 SMILES")
    if kind == "auto":
        if rank_local_names(text, MAX_CANDIDATES):
            kind = "name"
        else:
            # Parse within the sidecar, never load RDKit in Cinema 4D.
            with rdBase.BlockLogs():
                mol = Chem.MolFromSmiles(text) if text.isascii() and not any(c.isspace() for c in text) else None
            kind = "smiles" if mol is not None else "formula" if is_valid_formula(text) else "name"
    if kind == "smiles":
        return [_from_smiles(text, "SMILES 导入", {"kind": "smiles", "input": text}, cache_dir)]
    if kind == "name":
        local_names = rank_local_names(text, MAX_CANDIDATES)
        if local_names:
            return [_from_smiles(CHINESE_NAMES[name], name,
                                 {"kind": "builtin_alias", "alias": text, "name": name}, cache_dir)
                    for name in local_names]
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            raise ChemistryError("此中文名称尚未收录；请改用英文名、SMILES 或 ChemDraw 文件")
    if kind not in ("name", "formula"):
        raise ChemistryError("不支持的解析类型")
    cids = _pubchem_cids(kind, text)
    return _pubchem_records(cids, {}, cache_dir, query=text, kind=kind)


def _generate(record: dict, cache_dir: Path) -> dict:
    if record.get("schema_version") != 1:
        raise ChemistryError("结构记录版本不兼容")
    molblock = record.get("molblock", "")
    if not isinstance(molblock, str) or len(molblock) > MAX_INPUT_BYTES:
        raise ChemistryError("结构记录缺少有效 MolBlock")
    graph_block = record.get("graph_molblock", molblock)
    if not isinstance(graph_block, str) or len(graph_block) > MAX_INPUT_BYTES:
        raise ChemistryError("结构记录缺少有效原始图")
    graph_mol = Chem.MolFromMolBlock(graph_block, sanitize=True, removeHs=False)
    mol = Chem.MolFromMolBlock(molblock, sanitize=True, removeHs=False)
    if graph_mol is None or mol is None:
        raise ChemistryError("结构记录已损坏")
    _connected_molecule(graph_mol)
    _connected_molecule(mol)
    _check_record_atom_order(record, mol)
    _check_graph_atom_order(graph_mol, mol)
    original_smiles = Chem.MolToSmiles(Chem.RemoveHs(Chem.Mol(graph_mol)), isomericSmiles=True)
    original_key = hashlib.sha256(original_smiles.encode("utf-8")).hexdigest()
    if record.get("structure_key") != original_key or record.get("smiles") != original_smiles:
        raise ChemistryError("结构标识与实际原子和键不一致")
    naked_graph = Chem.MolToSmiles(Chem.RemoveHs(Chem.Mol(graph_mol)), isomericSmiles=False)
    naked_coords = Chem.MolToSmiles(Chem.RemoveHs(Chem.Mol(mol)), isomericSmiles=False)
    if naked_graph != naked_coords:
        raise ChemistryError("三维坐标记录与原始分子图不一致")
    has_3d, _ = _coordinates(mol)
    if has_3d:
        mol = Chem.AddHs(mol, addCoords=True)
    else:
        mol = Chem.AddHs(mol)
        params = AllChem.ETKDGv3()
        params.randomSeed = 20261008
        params.enforceChirality = True
        if AllChem.EmbedMolecule(mol, params) != 0:
            raise ChemistryError("无法生成三维构象；请提供已有三维坐标的 MOL/SDF")
        try:
            if AllChem.MMFFHasAllMoleculeParams(mol):
                AllChem.MMFFOptimizeMolecule(mol, maxIters=200)
            elif AllChem.UFFHasAllMoleculeParams(mol):
                AllChem.UFFOptimizeMolecule(mol, maxIters=200)
        except Exception:
            pass  # Embedded coordinates are still useful if optimization fails.
    if mol.GetNumAtoms() > MAX_ATOMS:
        raise ChemistryError(f"分子超过 {MAX_ATOMS} 个原子（含氢）的上限")
    generated = _record(mol, name=str(record.get("name", "分子")),
                        source=record.get("source", {"kind": "unknown"}), cache_dir=cache_dir,
                        warnings=record.get("warnings", []))
    # A 3D molfile can cause RDKit to infer an R/S configuration that the user
    # never specified. Keep the original graph as identity and for 2D previews.
    generated["smiles"] = original_smiles
    generated["structure_key"] = original_key
    generated["stereo_status"] = record.get("stereo_status", _stereo(graph_mol)[0])
    generated["warnings"] = list(record.get("warnings", []))
    generated["graph_molblock"] = graph_block
    # Display-only resource identity must survive embedding 3D coordinates.
    # It is not part of the molecule graph or geometry integrity hash.
    for field, limit in (("configuration_id", 128), ("list_source", 100)):
        if field in record:
            value = record[field]
            if (not isinstance(value, str) or not value or len(value) > limit or
                    any(ord(char) < 32 for char in value)):
                raise ChemistryError("结构资源标识无效")
            generated[field] = value
    (generated["thumbnail"], generated["themed_thumbnail"],
     generated["transparent_dark_thumbnail"], generated["transparent_thumbnail"],
     generated["thumbnail_atom_positions"]) = _thumbnail(graph_mol, cache_dir, original_key)
    generated["coordinates_ready"] = True
    generated["record_integrity"] = record_integrity(generated)
    return generated


def handle(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ChemistryError("请求格式错误")
    cache_text = request.get("cache_dir")
    if not isinstance(cache_text, str) or not Path(cache_text).is_absolute():
        raise ChemistryError("需要绝对路径的缓存目录")
    cache_dir = Path(cache_text).resolve()
    action = request.get("action")
    if action == "resolve":
        kind, value = request.get("kind"), request.get("text")
        # File inputs can change at the same path, so they are never cached.
        cacheable = kind in ("auto", "name", "formula", "smiles") and isinstance(value, str)
        text = normalize_query_text(value) if cacheable else ""
        if cacheable and 0 < len(text) <= 512:
            cached = resolve_cache.load(cache_dir, kind, text)
            if cached is not None:
                if any(record.get("depiction_version") != DEPICTION_VERSION for record in cached):
                    cached = [_generate_preview(record, cache_dir) for record in cached]
                    resolve_cache.save(cache_dir, kind, text, cached)
                return {"ok": True, "records": cached}
        records = _resolve({**request, "text": text} if cacheable else request, cache_dir)
        if cacheable and 0 < len(text) <= 512:
            resolve_cache.save(cache_dir, kind, text, records)
        return {"ok": True, "records": records}
    if action == "builtin":
        return {"ok": True, "records": [
            _from_smiles(CHINESE_NAMES[name], name,
                         {"kind": "builtin", "alias": name, "name": name}, cache_dir)
            for name in BUILTIN_NAMES]}
    if action == "generate":
        return {"ok": True, "record": _generate(request.get("record") or {}, cache_dir)}
    if action == "preview":
        record = request.get("record") or {}
        generated = _generate_preview(record, cache_dir)
        return {"ok": True, "record": generated}
    if action == "previews":
        records = request.get("records")
        if not isinstance(records, list) or len(records) > 24:
            raise ChemistryError("批量预览最多支持 24 个结构")
        return {"ok": True, "records": [_generate_preview(item, cache_dir)
                                         for item in records]}
    raise ChemistryError("不支持的操作")


def _generate_preview(record: dict, cache_dir: Path) -> dict:
    # Preview never calls a 3D embedder or changes graph/coordinates.
    mol = Chem.MolFromMolBlock(record.get("graph_molblock", record.get("molblock", "")),
                               sanitize=True, removeHs=False)
    if mol is None:
        raise ChemistryError("结构记录已损坏")
    _check_record_atom_order(record, mol)
    key = hashlib.sha256(Chem.MolToSmiles(Chem.RemoveHs(Chem.Mol(mol)), isomericSmiles=True).encode()).hexdigest()
    if record.get("structure_key") != key:
        raise ChemistryError("结构标识与记录不一致")
    thumbnail, themed_thumbnail, preview_light, preview_dark, positions = _thumbnail(mol, cache_dir, key)
    return {**record, "thumbnail": thumbnail, "themed_thumbnail": themed_thumbnail,
            "transparent_thumbnail": preview_dark,
            "transparent_dark_thumbnail": preview_light,
            "thumbnail_atom_positions": positions,
            "thumbnail_size": list(THUMBNAIL_SIZE),
            "depiction_version": DEPICTION_VERSION}


def _process_line(line: str) -> dict:
    if not line or len(line.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ChemistryError("请求为空或超过 8 MB")
    return handle(json.loads(line))


def main() -> None:
    loop = "--worker-loop" in sys.argv[1:]
    if not loop:
        try:
            line = sys.stdin.readline(MAX_INPUT_BYTES + 1)
            result = _process_line(line)
        except ChemistryError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception as exc:
            print(f"Chemistry worker: {type(exc).__name__}: {exc}", file=sys.stderr)
            result = {"ok": False, "error": "化学处理失败，请检查输入文件或网络"}
        sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()
        return

    while True:
        line = sys.stdin.readline(MAX_INPUT_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_INPUT_BYTES and not line.endswith("\n"):
            # Drain remainder of oversized line to keep stream aligned.
            while True:
                chunk = sys.stdin.readline(65536)
                if not chunk or chunk.endswith("\n"):
                    break
            result = {"ok": False, "error": "请求为空或超过 8 MB"}
        elif not line.strip():
            continue
        else:
            try:
                result = _process_line(line)
            except ChemistryError as exc:
                result = {"ok": False, "error": str(exc)}
            except Exception as exc:
                print(f"Chemistry worker: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                result = {"ok": False, "error": "化学处理失败，请检查输入文件或网络"}
        sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
