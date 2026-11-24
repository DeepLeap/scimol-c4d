<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/yuke-lockup-light.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/brand/yuke-lockup-dark.svg">
  <img alt="YUKE | 与可" src="./assets/brand/yuke-lockup-dark.svg" height="40">
</picture>

# SciMol C4D

**3D Molecular Builder for Cinema 4D & Redshift — Ball-and-Stick, Space-Fill & Wireframe**

<p>
  <img src="https://img.shields.io/badge/Cinema_4D-2025.3+_~_2027-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Cinema 4D" />
  <img src="https://img.shields.io/badge/Python-3.11-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Python" />
  <img src="https://img.shields.io/badge/RDKit-Chemistry_Engine-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="RDKit" />
  <img src="https://img.shields.io/badge/Redshift-Standard_Materials-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="Redshift" />
  <img src="https://img.shields.io/badge/License-MIT-111827?style=flat-square&labelColor=111827&color=94A3B8" alt="MIT" />
</p>

<p>
  <a href="./README.md">简体中文</a> | <b>English</b>
</p>

</div>

---

## Overview

SciMol C4D brings chemical structure search and 3D molecular visualization directly into Cinema 4D. Search by name, formula, SMILES, or import ChemDraw files to instantly generate real-time, adjustable ball-and-stick / space-fill / wireframe models — with a companion 2D structure editor for planar layout and flattening.

Built for scientific journal covers, TOC figures, and mechanism animations.

Chemistry parsing and 3D conformer generation run in a local RDKit process; inside C4D, the plugin uses native Python dialogs and Redshift Standard node materials.

## Features

| Category | Capability |
| :--- | :--- |
| **Unified search** | Chinese/English names · molecular formula · SMILES · ChemDraw CDXML/MOL/SDF — auto-detected in a single input |
| **3D generation** | Ball-and-stick · space-fill · wireframe skeleton — one-click mode switching |
| **Real-time tuning** | Size · thickness · spacing · segments · caps · show-H · per-element scale, all throttled at ~40 ms |
| **Scientific palettes** | Classic CPK · Nature Silver Academic · Science Crystal · Bright White · YUKE Bamboo Green — five presets with single-step undo |
| **2D editing** | Structure Details floating window: click/box/ring/invert atom selection, right-click planar groups, full or partial flattening |
| **Smart linking** | Context-aware greyed-out params · material inheritance · split-color bonds · freeze on finish · re-adopt selected |
| **Favorites** | Folders · save/save-as presets · import/export · usage ranking |
| **Hot process** | `--worker-loop` persistent RDKit worker, eliminating ~4 s cold-start; 81-entry offline dictionary |

## Installation

### 1. Clone

```bash
git clone https://github.com/DeepLeap/scimol-c4d.git
```

### 2. Set up the chemistry runtime

> [!IMPORTANT]
> RDKit installs into a project-local `.runtime/` venv — it does **not** need to be in C4D's built-in Python.

```powershell
# Windows PowerShell (admin)
cd scimol-c4d
.\安装运行环境.ps1
```

The script creates `.runtime/` and installs dependencies from `requirements.txt`.

### 3. Launch in C4D

- **Option A**: Open and run `分子球棍生成器.py` in C4D's Script Manager
- **Option B**: Load via the AI Plugin Hub

> [!NOTE]
> Standalone `.pyp` menu registration requires a valid Maxon plugin ID — see `插件/说明.md`.

## Workflow

```
Search/Import → Click thumbnail → Live preview → Adjust / Color / 2D edit → Finish
                     ↑                                           ↓
                     └──── Click another thumbnail to swap ←─────┘
                                                   Re-adopt → rebind
```

1. Search a name / formula / SMILES in the unified input, or import a ChemDraw file
2. Click a thumbnail to create a live preview; clicking another replaces the same model
3. Adjust appearance parameters in the right panel — WYSIWYG
4. Open "Structure Details" for 2D planar editing and grouping
5. Click "Finish" to freeze the model; the next click creates a new one

## Project Structure

```
scimol-c4d/
├── 分子球棍生成器.py       # C4D entry script
├── 脚本信息.json           # Plugin metadata
├── scimol_c4d/             # Core modules
│   ├── __init__.py         # Version & author info
│   ├── backend.py          # RDKit subprocess manager
│   ├── chemistry_worker.py # Chemistry hot worker
│   ├── c4d_builder.py      # 3D model builder
│   ├── browser_ui.py       # Main panel UI logic
│   ├── browser_layout.py   # Main panel layout
│   ├── atom_selector.py    # 2D selection & planar editor
│   ├── floating_windows.py # Win32 floating window attachment
│   ├── native_ui.py        # Brand logo component
│   └── ...                 # Other modules
├── assets/                 # Icons & brand assets
│   └── brand/              # YUKE brand SVGs
├── 测试/                   # Unit tests & host acceptance scripts
│   ├── fixtures/           # Test fixtures
│   ├── 验证本地.py         # Full local verification
│   └── test_*.py           # Per-module tests
├── 安装运行环境.ps1        # One-click chemistry setup
├── requirements.txt        # Python dependencies
└── 插件/说明.md            # Maxon plugin ID guide
```

## Testing

```powershell
# Run full verification with the project-local runtime
.\.runtime\Scripts\python.exe 测试\验证本地.py
```

This covers:

- All unit tests (281+)
- Python 3.11 AST syntax check on 70 source files
- Dependency and asset integrity validation

C4D host acceptance scripts (`测试/C4D*.py`) must be run inside Cinema 4D via MCP or the Script Manager.

## Compatibility

| Environment | Version |
| :--- | :--- |
| Cinema 4D | 2025.3.3+ (verified on 2027.0.0) |
| Python | 3.11 |
| Renderer | Redshift Standard node materials |
| OS | Windows |

## Limitations

- Single covalently connected molecule, up to 300 atoms (including H)
- Salts, multi-component, variable groups, crystals, and proteins are out of scope
- No image recognition, freehand drawing, fragment assembly, or render output
- First online search depends on PubChem network availability

## License

[MIT](./LICENSE) © 2026 [YUKE (DeepLeap)](https://github.com/DeepLeap)

---

<div align="center">
  <sub>Designed & built by <b>YUKE | 与可</b> · <a href="https://github.com/DeepLeap">DeepLeap</a></sub>
</div>
