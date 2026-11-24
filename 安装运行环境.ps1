$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.runtime\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & py -3.12 -m venv (Join-Path $taskRoot '.runtime')
    if ($LASTEXITCODE -ne 0) { throw '需要 Windows x64 Python 3.12。' }
}
& $taskPython -m pip install -r (Join-Path $taskRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '运行环境安装失败。' }
& $taskPython -c "from rdkit import rdBase; from PIL import Image; print('RDKit', rdBase.rdkitVersion)"
if ($LASTEXITCODE -ne 0) { throw '运行环境自检失败。' }
