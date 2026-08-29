$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
Assert-PythonEnvironment
Assert-Configuration
$taskName = "Bixi Seed 核心服务"
$startScript = Join-Path $PSScriptRoot "start.ps1"
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
& schtasks.exe /Create /TN $taskName /SC ONLOGON /TR $taskCommand /RL LIMITED /F
if ($LASTEXITCODE -ne 0) { throw "创建开机自启任务失败。" }
Write-Host "已设置登录后自动启动。"
