$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) { throw "未找到 npm，请先安装 Node.js LTS。" }
Push-Location (Join-Path $projectRoot "frontend")
try {
    & npm run build
} finally {
    Pop-Location
}

if (Test-Path (Join-Path $projectRoot ".venv\Scripts\python.exe")) {
    & (Join-Path $projectRoot ".venv\Scripts\python.exe") manage.py collectstatic --noinput
}
