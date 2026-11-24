<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/yuke-lockup-light.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/brand/yuke-lockup-dark.svg">
  <img alt="与可 | YUKE" src="./assets/brand/yuke-lockup-dark.svg" height="40">
</picture>

# SciMol C4D

**Cinema 4D 科研化学分子三维球棍 / 填充生成与二维平面编辑插件**

<p>
  <img src="https://img.shields.io/badge/Cinema_4D-2025.3+_~_2027-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Cinema 4D" />
  <img src="https://img.shields.io/badge/Python-3.11-111827?style=flat-square&labelColor=111827&color=0F766E" alt="Python" />
  <img src="https://img.shields.io/badge/RDKit-化学引擎-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="RDKit" />
  <img src="https://img.shields.io/badge/Redshift-Standard_材质-111827?style=flat-square&labelColor=111827&color=2DD4BF" alt="Redshift" />
  <img src="https://img.shields.io/badge/License-MIT-111827?style=flat-square&labelColor=111827&color=94A3B8" alt="MIT" />
</p>

<p>
  <b>简体中文</b> | <a href="./README.en.md">English</a>
</p>

</div>

---

## 定位

SciMol C4D 让你在 Cinema 4D 中直接搜索化学名称、分子式、SMILES 或导入 ChemDraw 文件，即刻生成可实时调整参数的三维球棍 / 空间填充 / 细棍骨架分子模型，并在独立窗口中进行二维结构编辑与平面展开——为科研期刊封面、TOC 图和机理动画提供端到端的分子可视化工作流。

化学解析和三维构象由项目本地 RDKit 进程完成，C4D 内使用原生 Python 面板和 Redshift Standard 节点材质。

## 功能一览

| 类别 | 能力 |
| :--- | :--- |
| **统一搜索** | 中文名 · 英文名 · 分子式 · SMILES · ChemDraw CDXML/MOL/SDF，一个输入框自动识别 |
| **三维生成** | 球棍 · 空间填充 · 细棍骨架三种模式一键切换 |
| **实时调整** | 大小 · 粗细 · 间距 · 分段 · 封顶 · 显示氢 · 元素缩放，全部约 40ms 节流实时联动 |
| **科研配色** | CPK 经典 · Nature 银灰学术 · Science 冷调晶体 · 明快白底插图 · 与可竹青（品牌）五套预设，支持单步撤销 |
| **二维编辑** | 结构详情浮窗：点选 / 框选 / 选环 / 反选原子，右键平面分组，全部拍平或局部拍平 |
| **智能联动** | 参数置灰 · 材质继承 · 双色键分界 · 完成冻结 · 接管所选 |
| **收藏管理** | 文件夹 · 保存配置 · 另存配置 · 导入导出 · 常用排行 |
| **热进程复用** | `--worker-loop` 常驻 RDKit，消除约 4s 冷启动延迟，81 词离线词库 |

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/DeepLeap/scimol-c4d.git
```

### 2. 安装化学运行环境

> [!IMPORTANT]
> RDKit 安装在项目本地 `.runtime/`，**不需要**装进 C4D 内置 Python。

```powershell
# Windows PowerShell（管理员权限）
cd scimol-c4d
.\安装运行环境.ps1
```

脚本会自动创建 `.runtime/` 虚拟环境并安装 `requirements.txt` 中的依赖。

### 3. 在 C4D 中启动

- **方式一**：在 C4D 脚本管理器中打开并执行 `分子球棍生成器.py`
- **方式二**：通过 AI 插件中心加载

> [!NOTE]
> 独立 `.pyp` 菜单注册需要合法 Maxon 插件 ID，参见 `插件/说明.md`。

## 工作流

```
搜索/导入 → 单击缩略图 → 实时预览 → 调参/配色/平面编辑 → 完成
                 ↑                                    ↓
                 └──── 切换结构替换同一预览 ←──────────┘
                                           接管所选 → 重新绑定
```

1. 在输入框搜索名称 / 分子式 / SMILES，或导入 ChemDraw 文件
2. 单击缩略图生成实时预览，继续点击替换同一个模型
3. 右侧面板调整外观参数，所见即所得
4. 打开"结构详情"进行二维平面编辑和平面分组
5. 点击"完成"冻结模型；下次单击才新建

## 项目结构

```
scimol-c4d/
├── 分子球棍生成器.py      # C4D 入口脚本
├── 脚本信息.json          # 插件元数据
├── scimol_c4d/            # 核心模块
│   ├── __init__.py        # 版本与作者信息
│   ├── backend.py         # RDKit 子进程管理
│   ├── chemistry_worker.py # 化学计算热进程
│   ├── c4d_builder.py     # 三维模型构建
│   ├── browser_ui.py      # 主面板界面逻辑
│   ├── browser_layout.py  # 主面板布局
│   ├── atom_selector.py   # 二维选择与平面编辑
│   ├── floating_windows.py # Win32 浮窗跟随
│   ├── native_ui.py       # 品牌 Logo 组件
│   └── ...                # 其他模块
├── assets/                # 图标与品牌资源
│   └── brand/             # 与可 | YUKE 品牌 SVG
├── 测试/                  # 单元测试 & 宿主验收脚本
│   ├── fixtures/          # 测试固件
│   ├── 验证本地.py        # 完整本地验证
│   └── test_*.py          # 各模块测试
├── 安装运行环境.ps1       # 一键安装化学依赖
├── requirements.txt       # Python 依赖
└── 插件/说明.md           # Maxon 插件 ID 说明
```

## 测试

```powershell
# 使用项目本地运行环境执行完整验证
.\.runtime\Scripts\python.exe 测试\验证本地.py
```

验证内容包括：

- 全部单元测试（281+ 项）
- 70 个源文件 Python 3.11 AST 语法检查
- 依赖与资源完整性校验

C4D 宿主验收脚本（`测试/C4D*.py`）需要在 Cinema 4D 内通过 MCP 或脚本管理器执行。

## 兼容性

| 环境 | 版本 |
| :--- | :--- |
| Cinema 4D | 2025.3.3+（已在 2027.0.0 验证） |
| Python | 3.11 |
| 渲染器 | Redshift Standard 节点材质 |
| 操作系统 | Windows |

## 限制

- 处理单个共价连接分子，最多 300 个原子（含氢）
- 盐、多组分、可变基团、晶体与蛋白质不在当前范围
- 不含识图、手绘、片段拼接或渲染输出功能
- 首次在线搜索受 PubChem 网络影响

## 许可证

[MIT](./LICENSE) © 2026 [YUKE (DeepLeap)](https://github.com/DeepLeap)

---

<div align="center">
  <sub>由 <b>与可 | YUKE</b> 设计开发 · <a href="https://github.com/DeepLeap">DeepLeap</a></sub>
</div>
