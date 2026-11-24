<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/scimol-hero-zh-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/brand/scimol-hero-zh-light.svg">
  <img alt="SciMol C4D by 与可 | YUKE" src="./assets/brand/scimol-hero-zh-light.svg" width="100%">
</picture>

<p>
  <b>简体中文</b> · <a href="./README.en.md">English</a>
  &nbsp;&nbsp;|&nbsp;&nbsp;
  <a href="#安装指南">AI 一键安装</a> · <a href="#核心亮点">核心亮点</a> · <a href="#快速上手">ChemDraw 联动</a> · <a href="#目录说明">目录说明</a>
</p>

</div>

专为**学术期刊封面（Cover Art）、TOC 摘要图、论文插图与科研机理动画**打造：免去跨软件导出 OBJ/FBX 与手动贴材质，直接在 Cinema 4D 内搜索或从 ChemDraw 粘贴结构，一键生成精准三维分子与 **Redshift Standard 节点材质**。

## 核心亮点

| 能力 | 说明 |
| :--- | :--- |
| **ChemDraw 联动** | 支持在 ChemDraw 中选中分子按 `Ctrl+Alt+C` 复制为 SMILES 直接粘贴生成，或一键导入 `.cdxml` / `.mol` / `.sdf` 文件 |
| **统一智能搜索** | 中英文名、分子式（支持下标 `C₆H₁₂O₆`）、SMILES 一框自动识别；内置 81 词离线常用词库并联动 PubChem 在线检索 |
| **一键精美材质** | 球棍 / 空间填充 / 细棍骨架三模式切换；自动构建原子与双色化学键独立 Redshift 材质，自带 5 套科研配色预设（含单步撤销） |
| **丝滑实时调参** | 单击缩略图生成实时预览，切换分子自动替换当前预览不堆冗余；支持原子大小、键粗细、间距、氢显示及单元素缩放即时联动 |
| **实用附带工具** | 常用记录、自定义收藏夹与预设保存；右下角「结构详情」提供二维原子/环点选、单原子/单键微调与骨架拍平辅助 |

## 安装指南

### 方式一：复制给任何 AI 自动安装（推荐）

如果你正在使用 **Cursor、Claude Code、Codex、Trae、Windsurf、Antigravity** 或其他支持终端命令的 AI 助手，点击下方代码块右上角的复制按钮，发给它即可自动完成下载、依赖配置与 C4D 菜单挂载：

````text
请帮我在当前 Windows 电脑上自动安装并配置 Cinema 4D 插件「SciMol C4D」（仓库：https://github.com/DeepLeap/scimol-c4d）：
1. 检查本机是否有 64 位 Python（3.10~3.13）；若没有，请先征得我同意后用 winget 安装 Python 3.12。
2. 将 https://github.com/DeepLeap/scimol-c4d 下载（git clone 或下载 main 分支 ZIP 解压）到独立固定目录 `%APPDATA%\Maxon\SciMol-C4D`（注意：切勿把整个项目直接放进 C4D 的 library\scripts 目录，以免 C4D 启动时扫描虚拟环境导致卡顿）。
3. 在该目录下执行 `powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D`，自动创建本地 `.runtime` 化学环境、完成 RDKit 自检，并将带图标的轻量化启动器注册到我电脑上的 Cinema 4D「用户脚本」菜单。
4. 安装验证通过后，请用通俗中文告诉我安装路径，以及打开 Cinema 4D 后在哪个菜单点击启动。
````

### 方式二：手动安装（3 步完成）

1. **下载到独立固定目录**（如 `D:\Plugins\scimol-c4d` 或 `%APPDATA%\Maxon\SciMol-C4D`，**不要**把完整仓库直接放进 C4D 的 `library\scripts`）
   ```bash
   git clone https://github.com/DeepLeap/scimol-c4d.git
   ```
2. **初始化化学环境并挂载 C4D 菜单**（需已安装 64 位 Python 3.10~3.13；不改动 C4D 内置 Python，默认源较慢时自动切换清华镜像源）
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\安装运行环境.ps1 -RegisterC4D
   ```
3. **启动插件**：打开或重启 Cinema 4D，点击顶部菜单 **扩展 (Extensions) → 用户脚本 (User Scripts) → 分子球棍生成器**；也可在「脚本管理器」直接运行 `分子球棍生成器.py`。

## 快速上手

```text
搜索或 ChemDraw 粘贴/导入 → 单击缩略图生成预览 → 调参 / 科研配色 → 点击「完成」定稿
                                   ↑                                      ↓
                                   └────────── 继续点击替换同一预览 ────────┘
```

- **ChemDraw 快捷键**：选中结构按 `Ctrl+Alt+C`（`Edit → Copy As → SMILES`），回到插件点击「粘贴」即刻生成。
- **材质共享与撤销**：默认开启「材质继承」，同元素材质可跨分子共享；切换科研配色后支持 `Ctrl+Z` 单步撤回。
- **二次接管模型**：点击「完成」冻结后，仍可通过「接管所选」重新绑定场景中未手工拆改的分子继续调参。

## 目录说明

```text
scimol-c4d/
├── 分子球棍生成器.py     # C4D 入口脚本
├── 安装运行环境.ps1      # 一键初始化本地 .runtime 化学环境并注册 C4D 用户脚本菜单
├── requirements.txt      # 化学引擎依赖（rdkit / Pillow / numpy）
├── 脚本信息.json         # 插件基础元数据
├── 界面图标.png / 图标.png # 菜单栏与展示图标
├── scimol_c4d/           # 核心模块（化学后台、三维建模、原生 UI 与浮窗交互）
├── assets/               # 界面图标与「与可 | YUKE」品牌矢量资产
└── 测试/                 # 本地单元测试（验证本地.py）与 C4D 宿主验收脚本
```

## 系统要求与适用范围

| 项目 | 说明 |
| :--- | :--- |
| **Cinema 4D & 渲染器** | Cinema 4D 2025.3+ ~ 2027（已在 2027.0.0 实测验证）· Redshift Standard 节点材质 |
| **系统与运行环境** | Windows · 本机安装 64 位 Python 3.10~3.13（仅用于隔离运行项目本地 `.runtime` 中的 RDKit） |
| **支持范围** | 单个共价连接分子，最多 300 个原子（含氢）；暂不支持盐、晶体晶胞、蛋白质大分子及图片 OCR 识图 |

<details>
<summary>开发者自检命令</summary>

```powershell
.\.runtime\Scripts\python.exe 测试\验证本地.py
```

</details>

---

<div align="center">
  <sub><a href="./LICENSE">MIT License</a> © 2026 <a href="https://github.com/DeepLeap">YUKE (DeepLeap)</a> · 与可科研可视化</sub>
</div>
