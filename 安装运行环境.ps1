param(
    [switch]$RegisterC4D
)

$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$venvDir = Join-Path $taskRoot '.runtime'
$taskPython = Join-Path $venvDir 'Scripts\python.exe'
$reqFile = Join-Path $taskRoot 'requirements.txt'

function Find-SupportedPython {
    $candidates = @(
        @{ Cmd = 'py'; Args = @('-3.12') },
        @{ Cmd = 'py'; Args = @('-3.11') },
        @{ Cmd = 'py'; Args = @('-3.13') },
        @{ Cmd = 'py'; Args = @('-3.10') },
        @{ Cmd = 'python'; Args = @() },
        @{ Cmd = 'python3'; Args = @() }
    )
    $probe = "import sys, struct; ok = (3, 10) <= sys.version_info[:2] <= (3, 13) and struct.calcsize('P') * 8 == 64; raise SystemExit(0 if ok else 1)"
    foreach ($item in $candidates) {
        $cmdInfo = Get-Command $item.Cmd -ErrorAction SilentlyContinue
        if (-not $cmdInfo) { continue }
        try {
            & $item.Cmd @($item.Args) -c $probe 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return $item
            }
        } catch {
            continue
        }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $taskPython)) {
    Write-Host '[1/3] 正在检测 64 位 Python 3.10~3.13...' -ForegroundColor Cyan
    $pyInfo = Find-SupportedPython
    if (-not $pyInfo) {
        throw '未检测到 64 位 Python 3.10~3.13，请先从 https://www.python.org/downloads/ 安装 Python 3.12（勾选 Add python.exe to PATH）后再试。'
    }
    Write-Host "[1/3] 正在创建独立化学虚拟环境 (.runtime)..." -ForegroundColor Cyan
    & $pyInfo.Cmd @($pyInfo.Args) -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskPython)) {
        throw '创建 .runtime 虚拟环境失败，请检查 Python 安装是否包含 venv 模块。'
    }
} else {
    Write-Host '[1/3] 已检测到本地 .runtime 虚拟环境，跳过创建。' -ForegroundColor Cyan
}

Write-Host '[2/3] 正在安装化学依赖 (rdkit / Pillow / numpy)...' -ForegroundColor Cyan
& $taskPython -m pip install -r $reqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host '默认 PyPI 源安装失败，正在自动切换国内清华镜像源重试...' -ForegroundColor Yellow
    & $taskPython -m pip install -r $reqFile -i https://pypi.tuna.tsinghua.edu.cn/simple
    if ($LASTEXITCODE -ne 0) {
        throw '运行环境安装失败，请检查网络连接后重试。'
    }
}

Write-Host '[3/3] 正在自检 RDKit 与图像处理模块...' -ForegroundColor Cyan
& $taskPython -c "from rdkit import rdBase; from PIL import Image; print('RDKit', rdBase.rdkitVersion, '环境就绪')"
if ($LASTEXITCODE -ne 0) {
    throw '运行环境自检失败。'
}

if ($RegisterC4D) {
    if ($taskRoot -match '(?i)\\Maxon[^\\]*\\library\\scripts') {
        Write-Warning '检测到当前项目位于 C4D library\scripts 目录内。建议将项目移至独立固定目录（如 %APPDATA%\Maxon\SciMol-C4D）后再执行 -RegisterC4D，以免 C4D 启动时扫描 .runtime 虚拟环境导致卡顿。'
    }

    $maxonRoot = Join-Path $env:APPDATA 'Maxon'
    if (-not (Test-Path -LiteralPath $maxonRoot)) {
        Write-Warning "未找到 Cinema 4D 配置目录：$maxonRoot。请先至少启动过一次 Cinema 4D，或手动在「脚本管理器」中打开 $taskRoot\分子球棍生成器.py。"
        return
    }

    $c4dDirs = Get-ChildItem -LiteralPath $maxonRoot -Directory | Where-Object {
        $_.Name -match '^Maxon Cinema 4D .*_[0-9A-Fa-f]{8}$' -and
        $_.Name -notmatch '_[px]$' -and
        (Test-Path -LiteralPath (Join-Path $_.FullName 'library\scripts'))
    }

    if (-not $c4dDirs) {
        Write-Warning "在 $maxonRoot 下未检测到包含 library\scripts 的 Cinema 4D 配置目录。请手动在「脚本管理器」中运行 $taskRoot\分子球棍生成器.py。"
        return
    }

    $entryPath = Join-Path $taskRoot '分子球棍生成器.py'
    $iconSrc = Join-Path $taskRoot '界面图标.png'
    $escapedEntry = $entryPath.Replace('\', '\\').Replace('"', '\"')

    $launcherCode = @"
"""SciMol C4D 用户脚本轻量化启动器 — 自动生成，请勿在此目录存放虚拟环境。"""

import importlib.util
import os
import sys


TARGET_ENTRY = "$escapedEntry"


def main():
    if not os.path.isfile(TARGET_ENTRY):
        import c4d
        c4d.gui.MessageDialog(
            "未找到 SciMol C4D 主程序：\n" + TARGET_ENTRY + "\n\n如已移动插件文件夹，请重新执行 安装运行环境.ps1 -RegisterC4D。"
        )
        return
    target_root = os.path.dirname(TARGET_ENTRY)
    if target_root not in sys.path:
        sys.path.insert(0, target_root)
    spec = importlib.util.spec_from_file_location("scimol_c4d_entry", TARGET_ENTRY)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 SciMol C4D 入口脚本: " + TARGET_ENTRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(globals().get("doc"))


if __name__ == "__main__":
    main()
"@

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $registered = @()
    foreach ($dir in $c4dDirs) {
        $scriptsDir = Join-Path $dir.FullName 'library\scripts'
        $launcherPath = Join-Path $scriptsDir '分子球棍生成器.py'
        $iconDst = Join-Path $scriptsDir '分子球棍生成器.png'
        [System.IO.File]::WriteAllText($launcherPath, $launcherCode, $utf8NoBom)
        if (Test-Path -LiteralPath $iconSrc) {
            Copy-Item -LiteralPath $iconSrc -Destination $iconDst -Force
        }
        $registered += $dir.Name
    }

    Write-Host ''
    Write-Host '已成功将轻量化启动器与图标注册到以下 Cinema 4D 配置目录：' -ForegroundColor Green
    foreach ($name in $registered) {
        Write-Host "  - $name" -ForegroundColor Green
    }
    Write-Host '请打开（或重启）Cinema 4D，点击顶部菜单「扩展 (Extensions) → 用户脚本 (User Scripts) → 分子球棍生成器」即可启动。' -ForegroundColor Green
}
