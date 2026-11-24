<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/scimol-hero-en-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/brand/scimol-hero-en-light.svg">
  <img alt="SciMol C4D by YUKE | 与可" src="./assets/brand/scimol-hero-en-light.svg" width="100%">
</picture>

<p>
  <a href="./README.md">简体中文</a> · <b>English</b>
  &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#installation">AI One-Click Install</a> · <a href="#highlights">Highlights</a> · <a href="#quick-workflow">ChemDraw Workflow</a> · <a href="#repository-layout">Layout</a>
</p>

</div>

Built for **scientific journal cover art, TOC graphics, paper figures, and mechanism animations**: skip manual OBJ/FBX exports and material re-binding — search directly inside Cinema 4D or paste from ChemDraw to generate accurate 3D molecules with **Redshift Standard node materials**.

## Highlights

| Feature | Details |
| :--- | :--- |
| **ChemDraw Workflow** | Copy any molecule as SMILES (`Ctrl+Alt+C`) and paste straight into SciMol, or import `.cdxml` / `.mol` / `.sdf` files directly |
| **All-in-One Search** | Auto-detects English/Chinese names, formulas (including subscripts like `C₆H₁₂O₆`), and SMILES; includes an 81-entry offline dictionary plus online PubChem lookup |
| **One-Click Materials** | Switch between Ball-and-Stick, Space-Fill, and Wireframe modes; builds independent Redshift Standard materials for atoms and split-color bonds with 5 scientific palettes (`Ctrl+Z` undoable) |
| **Live WYSIWYG Tuning** | Click a thumbnail for a live preview and click another to swap without scene clutter; adjust atom radius, bond thickness, spacing, hydrogens, and per-element scale in real time |
| **Companion Utilities** | Includes recent history, custom favorites folders, and presets; optional **Structure Details** 2D popup offers per-atom/per-bond fine-tuning and planar flattening |

## Installation

### Option 1: Copy & Paste This Prompt to Any AI Assistant (Recommended)

Using **Cursor, Claude Code, Codex, Trae, Windsurf, Antigravity**, or any AI assistant with terminal access? Copy the prompt below and send it to your AI — it will download, configure RDKit, and register the plugin in Cinema 4D automatically:

````text
Please help me install and configure the Cinema 4D plugin "SciMol C4D" (https://github.com/DeepLeap/scimol-c4d) on this Windows machine:
1. Check whether 64-bit Python (3.10–3.13) is installed; if missing, ask for my confirmation and install Python 3.12 via winget.
2. Download https://github.com/DeepLeap/scimol-c4d (git clone or download & extract the main branch ZIP) into a dedicated folder `%APPDATA%\Maxon\SciMol-C4D` (do NOT place the full repo inside C4D's `library\scripts` folder, as scanning `.runtime` slows down C4D startup).
3. Run `powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D` inside that directory to create the local `.runtime` environment, verify RDKit, and register a lightweight icon launcher in Cinema 4D's User Scripts menu.
4. Once verified, tell me the installation folder path and which Cinema 4D menu item to click to launch it.
````

### Option 2: Manual Setup (3 Steps)

1. **Clone into a dedicated folder** (e.g., `D:\Plugins\scimol-c4d` or `%APPDATA%\Maxon\SciMol-C4D` — **avoid** putting the full repo inside C4D's `library\scripts`)
   ```bash
   git clone https://github.com/DeepLeap/scimol-c4d.git
   ```
2. **Set up local RDKit & register the C4D menu** (requires 64-bit Python 3.10–3.13; never touches C4D's built-in Python, with automatic mirror fallback)
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D
   ```
3. **Launch in Cinema 4D**: Open or restart C4D and click **Extensions → User Scripts → 分子球棍生成器** (or run `分子球棍生成器.py` via Script Manager).

## Quick Workflow

```text
Search or Paste/Import from ChemDraw → Click thumbnail → Tune / Apply Palette → Finish
                                              ↑                                    ↓
                                              └──── Click another to swap live ────┘
```

- **ChemDraw Shortcut**: Select a structure, press `Ctrl+Alt+C` (`Edit → Copy As → SMILES`), and click **Paste** next to the search bar in SciMol.
- **Material Sharing & Undo**: Shared element materials are reused across molecules by default; palette switches support native `Ctrl+Z` undo.
- **Re-adopt Selected**: Even after clicking **Finish**, you can re-bind unmodified scene models later with **Re-adopt Selected**.

## Repository Layout

```text
scimol-c4d/
├── 分子球棍生成器.py        # C4D entry script
├── 安装运行环境.ps1         # Sets up local .runtime RDKit env & registers C4D menu
├── requirements.txt         # Chemistry engine dependencies (rdkit / Pillow / numpy)
├── 脚本信息.json            # Plugin metadata
├── 界面图标.png / 图标.png  # Launcher & showcase icons
├── scimol_c4d/              # Core Python modules (RDKit worker, 3D builder, native UI)
├── assets/                  # UI icons & YUKE brand SVG/PNG assets
└── 测试/                    # Local unit tests (验证本地.py) & C4D host verification scripts
```

## Requirements & Scope

| Item | Details |
| :--- | :--- |
| **Cinema 4D & Renderer** | Cinema 4D 2025.3+ ~ 2027 (verified on 2027.0.0) · Redshift Standard node materials |
| **OS & Runtime** | Windows · 64-bit Python 3.10–3.13 (used solely for the isolated local `.runtime` RDKit worker) |
| **Scope** | Single covalently connected molecules up to 300 atoms (incl. H); salts, crystal cells, proteins, and image OCR are out of scope |

<details>
<summary>Developer Verification Command</summary>

```powershell
.\.runtime\Scripts\python.exe 测试\验证本地.py
```

</details>

---

<div align="center">
  <sub><a href="./LICENSE">MIT License</a> © 2026 <a href="https://github.com/DeepLeap">YUKE (DeepLeap)</a> · Scientific Visualization</sub>
</div>
