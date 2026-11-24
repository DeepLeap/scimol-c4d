"""Small, synchronous index for locally supported Chinese molecule names."""

import re

from .records import _ELEMENT_SYMBOLS

BUILTIN_NAMES = (
    "水", "甲醇", "乙醇", "丙酮", "乙酸", "苯", "苯酚", "苄醇",
    "阿司匹林", "咖啡因", "邻二甲苯", "间二甲苯", "对二甲苯", "二甲醚",
)

LOCAL_STRUCTURES = {
    # 基础、气体与常见含氧/含氮小分子
    "水": "O",
    "过氧化氢": "OO",
    "氨": "N",
    "甲烷": "C",
    "乙烷": "CC",
    "乙烯": "C=C",
    "乙炔": "C#C",
    "二氧化碳": "O=C=O",
    "甲醛": "C=O",
    "乙醛": "CC=O",
    "甲酸": "O=CO",
    "乙酸": "CC(=O)O",
    "甲醇": "CO",
    "乙醇": "CCO",
    "异丙醇": "CC(C)O",
    "丙酮": "CC(C)=O",
    "二甲醚": "COC",
    "乙醚": "CCOCC",
    "环氧乙烷": "C1CO1",
    "尿素": "NC(N)=O",

    # 科研高频有机溶剂与试剂
    "四氢呋喃": "C1CCOC1",
    "二甲基亚砜": "CS(C)=O",
    "N,N-二甲基甲酰胺": "CN(C)C=O",
    "二氯甲烷": "ClCCl",
    "三氯甲烷": "ClC(Cl)Cl",
    "四氯化碳": "ClC(Cl)(Cl)Cl",
    "乙腈": "CC#N",
    "乙酸乙酯": "CCOC(C)=O",
    "1,4-二氧六环": "C1COCCO1",
    "三乙胺": "CCN(CC)CC",
    "三氟乙酸": "O=C(O)C(F)(F)F",
    "环己烷": "C1CCCCC1",
    "正己烷": "CCCCCC",

    # 芳香族、稠环与杂环骨架
    "苯": "c1ccccc1",
    "甲苯": "Cc1ccccc1",
    "邻二甲苯": "Cc1ccccc1C",
    "间二甲苯": "Cc1cccc(C)c1",
    "对二甲苯": "Cc1ccc(C)cc1",
    "苯酚": "Oc1ccccc1",
    "苄醇": "OCc1ccccc1",
    "苯甲醛": "O=Cc1ccccc1",
    "苯甲酸": "O=C(O)c1ccccc1",
    "水杨酸": "O=C(O)c1ccccc1O",
    "苯胺": "Nc1ccccc1",
    "硝基苯": "O=[N+]([O-])c1ccccc1",
    "氯苯": "Clc1ccccc1",
    "溴苯": "Brc1ccccc1",
    "苯乙烯": "C=Cc1ccccc1",
    "萘": "c1ccc2ccccc2c1",
    "蒽": "c1ccc2cc3ccccc3cc2c1",
    "吡啶": "c1ccncc1",
    "吡咯": "c1cc[nH]c1",
    "呋喃": "c1ccoc1",
    "噻吩": "c1ccsc1",
    "咪唑": "c1c[nH]cn1",
    "吲哚": "c1ccc2[nH]ccc2c1",

    # 生物医药、糖类、氨基酸、核酸碱基与天然产物
    "阿司匹林": "CC(=O)Oc1ccccc1C(=O)O",
    "咖啡因": "Cn1c(=O)c2c(ncn2C)n(C)c1=O",
    "布洛芬": "CC(C)Cc1ccc(C(C)C(=O)O)cc1",
    "对乙酰氨基酚": "CC(=O)Nc1ccc(O)cc1",
    "多巴胺": "NCCc1ccc(O)c(O)c1",
    "肾上腺素": "CNC[C@H](O)c1ccc(O)c(O)c1",
    "血清素": "NCCc1c[nH]c2ccc(O)cc12",
    "葡萄糖": "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O",
    "果糖": "OCC1(O)OC[C@@H](O)[C@@H](O)[C@@H]1O",
    "乳酸": "CC(O)C(=O)O",
    "柠檬酸": "O=C(O)CC(O)(C(=O)O)CC(=O)O",
    "甘油": "OCC(O)CO",
    "甘氨酸": "NCC(=O)O",
    "丙氨酸": "C[C@H](N)C(=O)O",
    "苯丙氨酸": "N[C@@H](Cc1ccccc1)C(=O)O",
    "色氨酸": "N[C@@H](Cc1c[nH]c2ccccc12)C(=O)O",
    "半胱氨酸": "N[C@@H](CS)C(=O)O",
    "胆固醇": "C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C",
    "腺嘌呤": "Nc1ncnc2[nH]cnc12",
    "胸腺嘧啶": "Cc1c[nH]c(=O)[nH]c1=O",
    "胞嘧啶": "Nc1cc[nH]c(=O)n1",
    "鸟嘌呤": "Nc1nc2[nH]cnc2c(=O)[nH]1",
    "尿嘧啶": "O=c1cc[nH]c(=O)[nH]1",
    "白藜芦醇": "Oc1ccc(/C=C/c2cc(O)cc(O)c2)cc1",
    "姜黄素": "COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O",
}

ALIASES = {
    "酒精": ("乙醇",),
    "醋酸": ("乙酸",),
    "苯甲醇": ("苄醇",),
    "双氧水": ("过氧化氢",),
    "氨气": ("氨",),
    "氯仿": ("三氯甲烷",),
    "丙三醇": ("甘油",),
    "二氧六环": ("1,4-二氧六环",),
    "邻羟基苯甲酸": ("水杨酸",),
    "乙酰水杨酸": ("阿司匹林",),
    "扑热息痛": ("对乙酰氨基酚",),
    "5-羟色胺": ("血清素",),
    "二甲基甲酰胺": ("N,N-二甲基甲酰胺",),
    "二甲苯": ("邻二甲苯", "间二甲苯", "对二甲苯"),
    "苯环": ("苯", "苯酚", "苄醇", "邻二甲苯", "间二甲苯", "对二甲苯", "阿司匹林"),
    "杂环": ("吡啶", "吡咯", "呋喃", "噻吩", "咪唑", "吲哚"),
    "碱基": ("腺嘌呤", "胸腺嘧啶", "胞嘧啶", "鸟嘌呤", "尿嘧啶"),
    "氨基酸": ("甘氨酸", "丙氨酸", "苯丙氨酸", "色氨酸", "半胱氨酸"),
    # 科研高频化学缩写（均非歧义 SMILES 写法）
    "THF": ("四氢呋喃",),
    "DMSO": ("二甲基亚砜",),
    "DMF": ("N,N-二甲基甲酰胺",),
    "DCM": ("二氯甲烷",),
    "CHCl3": ("三氯甲烷",),
    "CCl4": ("四氯化碳",),
    "MeCN": ("乙腈",),
    "ACN": ("乙腈",),
    "EA": ("乙酸乙酯",),
    "EtOAc": ("乙酸乙酯",),
    "TEA": ("三乙胺",),
    "TFA": ("三氟乙酸",),
    "Et2O": ("乙醚",),
    "EtOH": ("乙醇",),
    "MeOH": ("甲醇",),
    "AcOH": ("乙酸",),
    "H2O2": ("过氧化氢",),
    "NH3": ("氨",),
    "CO2": ("二氧化碳",),
}

_SUBSCRIPT_TABLE = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_PREFIX_RE = re.compile(r"^\s*(?:smiles|formula|name|分子式|化学式|名称)\s*[:：]\s*", re.IGNORECASE)
_FORMULA_RE = re.compile(r"(?:[A-Z][a-z]?\d*){1,15}$")
_FORMULA_TOKEN_RE = re.compile(r"([A-Z][a-z]?)(\d*)")


def normalize_query_text(text):
    """Trim whitespace, strip label prefixes, and convert Unicode subscripts."""
    cleaned = str(text or "").strip().translate(_SUBSCRIPT_TABLE)
    return _PREFIX_RE.sub("", cleaned).strip()


def is_valid_formula(text):
    """Validate chemical formulas against real periodic table element symbols."""
    cleaned = normalize_query_text(text)
    if not cleaned or not _FORMULA_RE.fullmatch(cleaned):
        return False
    tokens = _FORMULA_TOKEN_RE.findall(cleaned)
    if not tokens or "".join(symbol + count for symbol, count in tokens) != cleaned:
        return False
    for symbol, count in tokens:
        if symbol not in _ELEMENT_SYMBOLS:
            return False
        if count and int(count) <= 0:
            return False
    # Single-symbol bare words without counts (e.g. "In", "No", "As") are English words, not formulas.
    return len(tokens) >= 2 or any(count for _, count in tokens)


def smart_input_hint(text):
    """Return a concise, offline recognition hint for the current search box text."""
    cleaned = normalize_query_text(text)
    if not cleaned:
        return ""
    matches = rank_local_names(cleaned, limit=3)
    if matches:
        return "本地匹配：" + " / ".join(matches) + "（回车直达）"
    if is_valid_formula(cleaned):
        tokens = _FORMULA_TOKEN_RE.findall(cleaned)
        symbols = [symbol for symbol, _ in tokens]
        if any(count for _, count in tokens) and len(symbols) == len(set(symbols)):
            return "已识别为分子式 %s · 回车检索" % cleaned
        return "疑似 SMILES / 分子式 · 回车智能解析"
    if any("\u4e00" <= char <= "\u9fff" for char in cleaned):
        return "未收录中文名 · 可换英文名、SMILES 或导入文件"
    if cleaned.isascii() and not any(c.isspace() for c in cleaned):
        if any(ch in cleaned for ch in "=#()[]@/\\123456789"):
            return "疑似 SMILES 或结构串 · 回车自动识别"
    return "回车按英文名 / SMILES 自动识别"


def rank_local_names(text, limit=9, *, allow_ascii_prefix=False):
    """Rank canonical local names; never performs network or RDKit work."""
    cleaned = normalize_query_text(text)
    query = cleaned.casefold()
    if not query or limit <= 0:
        return []
    ascii_query = cleaned.isascii()
    scored = {}

    def offer(name, score):
        if name in LOCAL_STRUCTURES:
            scored[name] = min(score, scored.get(name, 1000))

    for index, name in enumerate(LOCAL_STRUCTURES):
        folded = name.casefold()
        if folded == query:
            offer(name, 0)
        elif ascii_query:
            if allow_ascii_prefix and len(query) >= 2 and folded.startswith(query):
                offer(name, 20 + index)
        elif folded.startswith(query):
            offer(name, 20 + index)
        elif query in folded:
            offer(name, 100 + index)
    for alias, targets in ALIASES.items():
        folded = alias.casefold()
        if folded == query:
            for index, name in enumerate(targets):
                offer(name, 1 + index)
        elif ascii_query:
            if allow_ascii_prefix and alias.isascii() and len(query) >= 2 and folded.startswith(query):
                for index, name in enumerate(targets):
                    offer(name, 40 + index)
        elif folded.startswith(query):
            for index, name in enumerate(targets):
                offer(name, 40 + index)
        elif query in folded:
            for index, name in enumerate(targets):
                offer(name, 120 + index)
    return sorted(scored, key=lambda name: (scored[name], name))[:limit]


def suggest_names(text, limit=8):
    """Return display names for a responsive, offline suggestion list."""
    return rank_local_names(text, limit, allow_ascii_prefix=True)
