<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/yuke-lockup-light.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/brand/yuke-lockup-dark.svg">
  <img alt="与可 | YUKE" src="./assets/brand/yuke-lockup-dark.svg" height="40">
</picture>

# SciMol C4D

**Cinema 4D 科研化学分子生成插件**

支持名称 / 分子式 / SMILES 搜索与 ChemDraw 复制导入，一键生成精美三维分子模型

<p>
  <img src="https://img.shields.io/badge/Cinema_4D-2025.3+_~_2027-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Cinema 4D" />
  <img src="https://img.shields.io/badge/Redshift-Standard_材质-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Redshift" />
  <img src="https://img.shields.io/badge/ChemDraw-复制_%2F_导入-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="ChemDraw" />
  <img src="https://img.shields.io/badge/RDKit-化学引擎-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="RDKit" />
  <img src="https://img.shields.io/badge/License-MIT-111827?style=flat-square&labelColor=111827&color=94A3B8" alt="MIT" />
</p>

<p>
  <b>简体中文</b> | <a href="./README.en.md">English</a>
</p>

</div>

---

## 简介

**SciMol C4D** 是一款专为**学术期刊封面（Cover Art）、TOC 摘要图、论文插图与科研机理动画**打造的 Cinema 4D 化学分子建模插件。

无需在多个软件之间来回导出 OBJ/FBX、也无需手动重绑材质——在插件内搜索分子或直接从 ChemDraw 复制结构，即可在 Cinema 4D 中一键生成比例精准、自带 **Redshift Standard 节点材质**的三维分子模型，并支持所见即所得的实时调参。

## 核心亮点

1. **无缝衔接 ChemDraw**：在 ChemDraw 中选中结构复制为 SMILES 直接粘贴即可生成；也支持直接导入 `.cdxml`、`.mol`、`.sdf` 结构文件。
2. **中英文 / 分子式 / SMILES 一框即搜**：内置 81 个常见科研分子与溶剂缩写（如 `THF`、`DMSO`、`DMF`、`阿司匹林`）离线词库，自动识别下标分子式（如 `C₆H₁₂O₆`）并支持联动 PubChem 在线检索。
3. **一键生成精美三维模型与 Redshift 材质**：支持球棍、空间填充、细棍骨架三种模式切换；自动构建原子与双色分割化学键独立材质，内置 **经典 CPK、Nature 银灰学术、Science 冷调晶体、明快白底插图、与可竹青** 5 套科研配色预设，多材质批量改色支持单步撤销。
4. **所见即所得实时调参**：单击缩略图即生成预览，切换分子自动替换当前预览不堆冗余模型；滑块实时调节原子大小、键粗细、多键间距、氢显示与元素单独缩放，满意后点击「完成」定稿，并可通过「接管所选」重新联动场景模型。
5. **实用附带工具**：提供本地常用记录、自定义收藏夹与外观预设保存；点击右下角「结构详情」可展开二维结构视图，辅助完成单原子/单键局部尺寸微调与分子骨架拍平。

---

## 安装指南

### 方式一：复制给任何 AI 自动安装（推荐）

如果你正在使用 **Cursor、Claude Code、Codex、Trae、Windsurf、Antigravity** 或其他支持终端命令的 AI 助手，直接点击下方代码块右上角的复制按钮，把整段提示词发给它即可自动完成下载、依赖配置与 C4D 菜单挂载：

````text
请帮我在当前 Windows 电脑上自动安装并配置 Cinema 4D 插件「SciMol C4D」（仓库：https://github.com/DeepLeap/scimol-c4d）：
1. 检查本机是否有 64 位 Python（3.10~3.13）；若没有，请先征得我同意后用 winget 安装 Python 3.12。
2. 将 https://github.com/DeepLeap/scimol-c4d 下载（git clone 或下载 main 分支 ZIP 解压）到独立固定目录 `%APPDATA%\Maxon\SciMol-C4D`（注意：切勿把整个项目直接放进 C4D 的 library\scripts 目录，以免 C4D 启动时扫描虚拟环境导致卡顿）。
3. 在该目录下执行 `powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D`，自动创建本地 `.runtime` 化学环境、完成 RDKit 自检，并将带图标的轻量化启动器注册到我电脑上的 Cinema 4D「用户脚本」菜单。
4. 安装验证通过后，请用通俗中文告诉我安装路径，以及打开 Cinema 4D 后在哪个菜单点击启动。
````

### 方式二：手动安装（3 步完成）

1. **下载项目到独立目录**
   ```bash
   git clone https://github.com/DeepLeap/scimol-c4d.git
   ```
   > [!TIP]
   > 建议将项目放在固定目录（例如 `D:\Plugins\scimol-c4d` 或 `%APPDATA%\Maxon\SciMol-C4D`），**不要**把整个仓库直接放进 C4D 的 `library\scripts` 目录。

2. **一键配置环境并注册菜单**（需提前安装 64 位 Python 3.10~3.13）
   在项目根目录打开 PowerShell 运行：
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D
   ```
   脚本会自动在项目本地创建 `.runtime/` 独立虚拟环境并安装 RDKit（**不会改动 C4D 内置 Python**，若默认源较慢会自动切换国内清华镜像源），随后将轻量化启动脚本与图标挂载进本机 Cinema 4D 的用户脚本目录。

3. **在 Cinema 4D 中启动**
   打开或重启 Cinema 4D，点击顶部菜单 **扩展 (Extensions) → 用户脚本 (User Scripts) → 分子球棍生成器** 即可启动；也可在「自定义命令」中将其拖到工具栏固定为图标按钮，或在「脚本管理器」中直接打开运行 `分子球棍生成器.py`。

---

## 快速上手

```
搜索或 ChemDraw 粘贴/导入 → 单击缩略图生成预览 → 调参 / 科研配色 → 点击「完成」定稿
                                   ↑                                      ↓
                                   └────────── 继续点击替换同一预览 ────────┘
```

- **ChemDraw 快捷联动**：在 ChemDraw 中选中目标分子，按 `Ctrl+Alt+C`（或菜单 `Edit → Copy As → SMILES`），回到插件点击搜索框旁的「粘贴」按钮，即可立刻生成三维结构。
- **材质共享与撤销**：默认开启「材质继承」，同一元素材质可跨分子共享；切换科研配色方案后可直接用 C4D 原生 `Ctrl+Z` 单步撤回。

---

## 目录说明

```text
scimol-c4d/
├── 分子球棍生成器.py     # C4D 入口脚本（在脚本管理器或用户脚本菜单中调用）
├── 安装运行环境.ps1      # 一键初始化本地 .runtime 化学环境并注册 C4D 菜单
├── requirements.txt      # 本地化学引擎依赖（rdkit / Pillow / numpy）
├── 脚本信息.json         # 插件名称、版本与基础元数据
├── 界面图标.png / 图标.png # 菜单栏与展示图标
├── scimol_c4d/           # 插件核心源码（化学后台、三维建模、原生 UI 与浮窗交互）
├── assets/               # 界面按钮图标与「与可 | YUKE」品牌视觉资源
└── 测试/                 # 本地单元测试（验证本地.py）与 C4D 宿主验收脚本
```

## 系统要求与适用范围

| 项目 | 说明 |
| :--- | :--- |
| **Cinema 4D** | 2025.3+ ~ 2027（已在 2027.0.0 完整验证） |
| **渲染器** | Redshift（自动构建 Standard 节点材质） |
| **操作系统** | Windows（需安装 64 位 Python 3.10~3.13 用于本地 RDKit 后台） |
| **支持范围** | 单个共价连接分子，最多 300 个原子（含氢）；不支持盐、晶体晶胞、蛋白质大分子及图片 OCR 识别 |

<details>
<summary>开发者自检命令</summary>

```powershell
# 运行全量本地单元测试、Python 3.11 AST 语法检查与资源完整性校验
.\.runtime\Scripts\python.exe 测试\验证本地.py
```

</details>

## 许可证

[MIT](./LICENSE) © 2026 [YUKE (DeepLeap)](https://github.com/DeepLeap)

---

<div align="center">
  <sub>由 <b>与可 | YUKE</b> 设计开发 · <a href="https://github.com/DeepLeap">DeepLeap</a></sub>
</div>
