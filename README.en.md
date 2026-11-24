<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/yuke-lockup-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/brand/yuke-lockup-light.svg">
  <img alt="YUKE | 与可" src="./assets/brand/yuke-lockup-light.svg" height="48">
</picture>

# SciMol C4D

**3D Chemical Molecule Generator for Cinema 4D**

Search by Name, Formula, or SMILES — or Copy & Import from ChemDraw — to Build Publication-Ready 3D Molecules in One Click

<p>
  <img src="https://img.shields.io/badge/Cinema_4D-2025.3%2B_~_2027-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Cinema 4D" />
  <img src="https://img.shields.io/badge/Redshift-Standard_Materials-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Redshift" />
  <img src="https://img.shields.io/badge/ChemDraw-Copy_%26_Import-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="ChemDraw" />
  <img src="https://img.shields.io/badge/RDKit-Chemistry_Engine-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="RDKit" />
  <img src="https://img.shields.io/badge/License-MIT-111827?style=flat-square&labelColor=111827&color=94A3B8" alt="MIT" />
</p>

<p>
  <a href="./README.md">简体中文</a> | <b>English</b>
</p>

</div>

---

## Overview

**SciMol C4D** is a Cinema 4D molecular modeling plugin built for **scientific journal cover art, TOC graphics, paper figures, and mechanism animations**.

Skip manual OBJ/FBX exports and tedious material re-binding. Search any molecule directly inside C4D — or copy a structure straight from ChemDraw — to generate accurate 3D models complete with **Redshift Standard node materials** and real-time WYSIWYG parameter tuning.

## Key Highlights

1. **Seamless ChemDraw Workflow**: Copy any structure as SMILES in ChemDraw and paste it straight into SciMol, or import `.cdxml`, `.mol`, and `.sdf` files directly.
2. **All-in-One Search**: Search by English/Chinese name, molecular formula (including subscripts like `C₆H₁₂O₆`), or SMILES. Ships with an 81-entry offline dictionary of common molecules & solvent abbreviations (`THF`, `DMSO`, `DMF`, etc.) plus online PubChem lookup.
3. **One-Click 3D Models & Redshift Materials**: Switch smoothly between Ball-and-Stick, Space-Fill, and Wireframe modes. Builds independent Redshift Standard materials for atoms and split-color bonds, with **5 scientific color presets** (Classic CPK, Nature Silver Academic, Science Crystal, Bright White, YUKE Bamboo Green) and single-step undo (`Ctrl+Z`).
4. **Live WYSIWYG Tuning**: Click a thumbnail for a live preview; clicking another swaps the active model without cluttering your scene. Adjust atom radius, bond thickness, multi-bond spacing, hydrogens, and per-element scale in real time, lock with **Finish**, or re-bind any scene molecule via **Re-adopt Selected**.
5. **Handy Companion Utilities**: Includes recent history, custom favorites folders, and appearance presets. An optional **Structure Details** 2D popup supports per-atom/per-bond fine-tuning and local/full planar flattening when needed.

---

## Installation

### Option 1: Copy & Paste This Prompt to Any AI Assistant (Recommended)

Using **Cursor, Claude Code, Codex, Trae, Windsurf, Antigravity**, or any AI coding assistant with terminal access? Copy the prompt below and send it to your AI — it will download, set up RDKit, and register the plugin inside Cinema 4D automatically:

````text
Please help me install and configure the Cinema 4D plugin "SciMol C4D" (https://github.com/DeepLeap/scimol-c4d) on this Windows machine:
1. Check whether 64-bit Python (3.10–3.13) is installed; if missing, ask for my confirmation and install Python 3.12 via winget.
2. Download https://github.com/DeepLeap/scimol-c4d (git clone or download & extract the main branch ZIP) into a dedicated folder `%APPDATA%\Maxon\SciMol-C4D` (do NOT place the full repo inside C4D's `library\scripts` folder, as scanning `.runtime` slows down C4D startup).
3. Run `powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D` inside that directory to create the local `.runtime` environment, verify RDKit, and register a lightweight icon launcher in Cinema 4D's User Scripts menu.
4. Once verified, tell me the installation folder path and which Cinema 4D menu item to click to launch it.
````

### Option 2: Manual Setup (3 Steps)

1. **Clone to a dedicated folder**
   ```bash
   git clone https://github.com/DeepLeap/scimol-c4d.git
   ```
   > [!TIP]
   > Keep the repository in a fixed folder such as `D:\Plugins\scimol-c4d` or `%APPDATA%\Maxon\SciMol-C4D` — **avoid** putting the whole repository directly inside C4D's `library\scripts`.

2. **Install the local chemistry runtime & register C4D menu** (requires 64-bit Python 3.10–3.13)
   Run in PowerShell inside the cloned folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D
   ```
   This creates a self-contained `.runtime/` virtualenv with RDKit (**without touching C4D's built-in Python**, with automatic mirror fallback if PyPI is slow) and registers a lightweight launcher script + icon into your Cinema 4D user scripts folder.

3. **Launch in Cinema 4D**
   Open or restart Cinema 4D and go to **Extensions → User Scripts → 分子球棍生成器** (or run `分子球棍生成器.py` directly from Script Manager). You can also drag the command onto any C4D toolbar via Customize Commands.

---

## Quick Workflow

```
Search or Paste/Import from ChemDraw → Click thumbnail → Tune / Apply Palette → Finish
                                              ↑                                    ↓
                                              └──── Click another to swap live ────┘
```

- **ChemDraw Shortcut**: Select a molecule in ChemDraw, press `Ctrl+Alt+C` (`Edit → Copy As → SMILES`), then click **Paste** next to the search bar in SciMol to build the 3D model immediately.
- **Material Inheritance & Undo**: Shared element materials are reused across molecules by default, and palette switches support native `Ctrl+Z` undo.

---

## Repository Layout

```text
scimol-c4d/
├── 分子球棍生成器.py        # C4D entry script (Script Manager / User Scripts launcher)
├── 安装运行环境.ps1         # Sets up local .runtime RDKit env & optionally registers C4D menu
├── requirements.txt         # Chemistry engine dependencies (rdkit / Pillow / numpy)
├── 脚本信息.json            # Plugin name, version, and metadata
├── 界面图标.png / 图标.png  # Launcher & showcase icons
├── scimol_c4d/              # Core Python modules (RDKit worker, 3D builder, native UI)
├── assets/                  # Toolbar icons & YUKE brand SVG/PNG assets
└── 测试/                    # Local unit tests (验证本地.py) & C4D host verification scripts
```

## Requirements & Scope

| Item | Details |
| :--- | :--- |
| **Cinema 4D** | 2025.3+ ~ 2027 (verified on 2027.0.0) |
| **Renderer** | Redshift (Standard node materials) |
| **OS** | Windows (with 64-bit Python 3.10–3.13 for the local RDKit worker) |
| **Scope** | Single covalently connected molecules up to 300 atoms (incl. H); salts, crystals, proteins, and image OCR are out of scope |

<details>
<summary>Developer Verification Command</summary>

```powershell
.\.runtime\Scripts\python.exe 测试\验证本地.py
```

</details>

## License

[MIT](./LICENSE) © 2026 [YUKE (DeepLeap)](https://github.com/DeepLeap)

---

<div align="center">
  <sub>Designed & built by <b>YUKE | 与可</b> · <a href="https://github.com/DeepLeap">DeepLeap</a></sub>
</div>
