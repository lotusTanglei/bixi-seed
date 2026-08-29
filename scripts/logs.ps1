$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
$logPath = Join-Path $LogDirectory "server.err.log"
if (-not (Test-Path $logPath)) { $logPath = Join-Path $LogDirectory "django.log" }
if (-not (Test-Path $logPath)) { Write-Host "暂无日志。"; exit 0 }
Get-Content $logPath -Wait
