$ErrorActionPreference = "Stop"
& schtasks.exe /Delete /TN "Bixi Seed 核心服务" /F
if ($LASTEXITCODE -eq 0) { Write-Host "已移除自动启动。" }
