# SciMol C4D — AI Cross-Version & Cross-DCC Adapter Guide

> 本指南面向 AI 编码助手（Cursor / Claude Code / Codex / Trae / Windsurf / Antigravity 等）与开发者。  
> **核心理念**：本项目将 **70% 的化学解析、ChemDraw 导入与三维几何算法** 与 **30% 的 3D 软件建模/材质接口** 彻底解耦。Cinema 4D 是开箱即用的主阵地；借助本蓝图，任何 AI 都可以将它快速适配到 **早期 Cinema 4D 版本、其他渲染器（Standard / Octane / Arnold / Corona）**，或直接移植到 **Blender / Maya / Houdini / 3ds Max** 等三维软件。

---

## 1. 架构分层（哪些代码可 100% 复用，哪些需要按软件改写）

### A. 通用化学与几何内核（零 3D 软件依赖，可直接复用）

以下模块 **不导入 `c4d` 或 `maxon`**，也不要求宿主 3D 软件自带任何第三方科学库：

| 模块 | 职责 | 对外核心能力 |
| :--- | :--- | :--- |
| `scimol_c4d/backend.py` | 跨进程调用调度器 | 管理项目本地 `.runtime/Scripts/python.exe` 常驻热进程，异步提交请求与取消旧任务 |
| `scimol_c4d/chemistry_worker.py` | 化学结构与 3D 构象引擎 | 解析中英文名 / 分子式 / SMILES / ChemDraw（`.cdxml` `.mol` `.sdf`），生成 3D 坐标、2D 缩略图与原子热点 |
| `scimol_c4d/search_index.py` | 离线词库与智能纠错 | 81 个常见分子与缩写词库、下标分子式归一化、合法性校验 |
| `scimol_c4d/resolve_cache.py` | 跨会话结果缓存 | 7 天本地搜索结果缓存与 LRU 淘汰 |
| `scimol_c4d/records.py` | 标准数据结构与样式定义 | `validate_record()`、`DEFAULT_STYLE`、参数校验 |
| `scimol_c4d/display_geometry.py` | 三维显示方位与拍平算法 | `orient_display_positions()`（苯环优先居中摆正）、`flatten_overrides()`（全/局部二维拍平）、`apply_plane_groups()` |
| `scimol_c4d/hydrogen_layout.py` | 氢原子局部重排避碰 | 骨架拍平后自动为 CH / CH₂ / CH₃ / OH 重新计算无碰撞氢方向 |
| `scimol_c4d/appearance_scale.py` | 1–5 直观刻度与物理值换算 | `to_display()` / `from_display()`，以及基于化学半径的球体显示缩放比例 |
| `scimol_c4d/library.py` & `usage.py` | 收藏与常用统计 | 预设导入导出、常用频率排行 |

### B. 3D 宿主适配层（仅此处接触目标软件 SDK）

| 模块 | 依赖的 C4D API | 移植/适配目标 |
| :--- | :--- | :--- |
| `scimol_c4d/c4d_builder.py` | `c4d`, `maxon` | **核心移植文件**：将标准分子 `record` + `style` 转化为场景球体、双色分段圆柱与材质 |
| `scimol_c4d/ui.py` | `c4d.gui` | 提供 `ELEMENT_COLORS` 默认 CPK 配色与基础面板基类 |
| `scimol_c4d/browser_ui.py` & `browser_layout.py` | `c4d.gui` | 主浏览器与参数面板，内含 `COLOR_PRESETS`（5 套科研配色 RGB） |
| `scimol_c4d/atom_selector.py` & `native_ui.py` | `c4d.gui` | 可选的二维「结构详情」交互编辑窗口与品牌标志控件 |
| `scimol_c4d/resource_browser.py` & `floating_windows.py` | `c4d.gui` / Win32 | 卡片网格与 Windows 浮窗跟随（跨软件移植时可用目标软件原生 UI 替代，非必需） |

---

## 2. 标准数据调用协议（5 行代码获取三维分子 JSON）

无论移植到什么 3D 软件，都无需重新实现化学解析——直接把项目本地 `.runtime` 当作后台服务调用：

```python
from pathlib import Path
from scimol_c4d.backend import Backend

backend = Backend()
# 1) 搜索名称 / 分子式 / SMILES，或解析 ChemDraw 文件（kind="file", path="..."）
backend.submit({"action": "resolve", "kind": "auto", "text": "阿司匹林"}, "search")
_, _, res, _ = backend.results.get(timeout=30)
candidate = res["records"][0]

# 2) 如 candidate["coordinates_ready"] 为 False，生成三维构象坐标
if not candidate.get("coordinates_ready"):
    backend.submit({"action": "generate", "record": candidate}, "gen3d")
    _, _, gen_res, _ = backend.results.get(timeout=60)
    record = gen_res["record"]
else:
    record = candidate

backend.close()
```

生成的标准 `record` 关键字段：
- `record["atoms"]`: `[{"id": 0, "element": "C", "x": 1.23, "y": -0.45, "z": 0.67}, ...]`（单位：Å）
- `record["bonds"]`: `[{"a": 0, "b": 1, "order": 1, "aromatic": False}, ...]`（`order` 为 `1 / 2 / 3`，芳香键已 Kekule 化为交替单双键并标记 `aromatic`）

> 提示：如果不希望在 3D 主线程里使用 `Backend` 线程队列，也可以直接用 `subprocess.run([".runtime/Scripts/python.exe", "scimol_c4d/chemistry_worker.py"], input=json_str, ...)` 通过标准输入输出一行 JSON 同步调用。

---

## 3. 核心三维几何与着色算法（跨软件通用配方）

移植到任何 3D 软件时，请复用以下精确逻辑以保持科研级比例与美感：

1. **单位与方位预处理**：
   - 先调用 `scimol_c4d.display_geometry.orient_display_positions(record, display, style["orientation"], style["center_atom_ids"])`，自动以苯环 / 优先环居中并水平摆正，再整体乘以 `style["scale"]`（默认 `50.0`）。
   - **坐标系注意**：C4D 采用左手坐标系，因此 `c4d_builder.py` 对 Z 轴取反（`+x, +y, -z`）；移植到 **Blender / Maya / Houdini** 等右手坐标系软件时，直接使用 `(x, y, z)`（或按 Z-up 映射 `(x, -z, y)` 即可）。
2. **原子球体半径**：
   - `r = atom_radius * scale * atom_display_factor(style, element, atom_radius) * element_scale * atom_override_factor`
   - 可直接调用或参考 `scimol_c4d/appearance_scale.py`（支持「球棍 / 空间填充 / 细棍」三种显示形态自动衔接）。
3. **双键 / 三键平行偏移向量（`_bond_offsets`）**：
   - 对每条键 `A -> B`（单位方向 `axis`），在两端重原子邻居中找一个不与 `axis` 共线的参考向量，向垂直于 `axis` 的平面投影并归一化得到 `hint`；按 `offset_i = hint * ((i - (order - 1) / 2.0) * spacing * scale)` 偏移各分键中心线，使共轭环的双键天然共面齐平。
4. **双色共价键球面外露等长分界公式（`_color_junction`）**：
   - 原子球大小悬殊时（如 `C—H`），若简单从几何中点切分化学键，碳侧外露短、氢侧外露长，视觉会失衡。SciMol 的处理公式如下：
   ```python
   cut_a = math.sqrt(max(r_a * r_a - offset_len * offset_len, 0.0))
   cut_b = math.sqrt(max(r_b * r_b - offset_len * offset_len, 0.0))
   # 若两球已经覆盖整条键，回退几何中点；否则使两侧外露长度 (d - cut_a) == (L - d - cut_b)
   if cut_a + cut_b >= L:
       t = 0.5
   else:
       d = (L + cut_a - cut_b) * 0.5
       t = max(1e-4, min(1.0 - 1e-4, d / L))
   junction = start + (end - start) * t
   ```
   - 由 `start -> junction` 赋予 A 原子颜色/键色，由 `junction -> end` 赋予 B 原子颜色/键色，两段圆柱高度各取分段长度、半径取 `bond_radius * scale`。
5. **内置科研配色表**：
   - 默认 CPK 基础配色：`scimol_c4d/ui.py` 中的 `ELEMENT_COLORS`。
   - 5 套科研预设（经典 CPK、Nature 银灰学术、Science 冷调晶体、明快白底插图、与可竹青）：`scimol_c4d/browser_ui.py` 中的 `COLOR_PRESETS`（0–1 线性/浮点 RGB）。

---

## 4. Cinema 4D 跨版本与多渲染器适配指引

当前 `scimol_c4d/c4d_builder.py` 的材质均集中隔离在以下 3 个函数中，修改它们即可零风险切换渲染器或适配早期 C4D 版本：

- **`_node_material(doc, name, color)`**（创建材质并接入文档撤销栈）
- **`_set_material_color(mat, color, record_undo=True)`**（修改现有材质基础色）
- **`_material_graph_snapshot(mat)`**（判断用户是否手工改动过材质节点图）

### 常见 C4D 适配改造点：
1. **切换为 Cinema 4D 原生标准材质（兼容 R23 ~ 最新版，无 Redshift 也能用）**：
   - 在 `_node_material()` 中不调用 `GetNodeMaterialReference().CreateEmptyGraph(_NODE_SPACE)`，直接创建 `mat = c4d.BaseMaterial(c4d.Mmaterial)`，设置 `mat[c4d.MATERIAL_USE_COLOR] = True` 与 `mat[c4d.MATERIAL_COLOR_COLOR] = c4d.Vector(*color)`。
   - 在 `_set_material_color()` 中直接修改 `mat[c4d.MATERIAL_COLOR_COLOR] = c4d.Vector(*_color(color))`（配合 `doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat)`）。
   - 在 `_material_graph_snapshot()` 中返回 `[mat[c4d.MATERIAL_COLOR_COLOR], ...]` 的轻量快照，并将 `c4d_builder.py` 顶部无用的 `import maxon`（如旧版 C4D 缺少部分节点枚举）设为条件导入即可。
2. **切换为 Octane / Arnold / Corona**：
   - 仅需将上述 3 个函数中的节点空间 ID / 端口名（或材质类型 ID，如 Octane Glossy / Universal Material）替换为对应渲染器的 Python API。
3. **旧版 C4D 常见 API 兼容**：
   - `c4d.Oinstance`、GeDialog 基础控件与 `BaseContainer` 在 R21+ 基本一致；若旧版缺少特定 `INSTANCEOBJECT_RENDERINSTANCE_MODE` 常量，可用 `getattr(c4d, ..., fallback)` 兜底。

---

## 5. 移植到 Blender / Maya / Houdini 等 3D 软件参考配方

当用户的 AI 需要将本项目移植到其他 3D 软件时，请按以下最短路径执行：

1. **保留不动的部分**：完整保留 `scimol_c4d/` 中除 `c4d_* / ui / browser_* / atom_selector / resource_browser / floating_windows / native_ui` 之外的所有模块，以及 `.runtime/`（由 `安装运行环境.ps1` 创建）和 `assets/`。
2. **以 Blender (`bpy`) 为例（同样适用于 Maya `maya.cmds` / Houdini `hou`）**：
   - **入口与面板**：新建 Blender Add-on（`bl_info` + `bpy.types.Panel` 挂载在 `VIEW_3D` → `UI` 侧栏），包含搜索框、ChemDraw 剪贴板粘贴/文件导入按钮、外观模式与 5 套科研配色下拉框。
   - **高效建模（实例化）**：为所有球体创建一个共用高细分 `bmesh` UV 球 Mesh 数据块，为化学键创建一个标准单位高度（`height=1.0`，轴向沿 `Z` 或 `Y`）圆柱 Mesh 数据块；通过 `bpy.data.objects.new(name, shared_mesh)` 批量实例化到分子专属 Collection 下，用 `obj.scale` 和四元数/旋转矩阵定位每个原子和半键圆柱。
   - **材质构建**：为每种元素创建复用材质（开启 `mat.use_nodes = True`），向 `Principled BSDF` 的 `Base Color` 写入配色表 RGB（RGBA 补 `1.0`）并适度调节 `Roughness`（如 `0.28`）以适配 Cycles / Eevee。
   - **保持「与可 | YUKE」开源署名**：保留仓库原有 MIT 版权与原作者署名信息。
