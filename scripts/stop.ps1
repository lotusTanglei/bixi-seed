$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"

$managed = Get-ManagedProcess $PidFile
if ($managed) {
    Stop-Process -Id $managed.ProcessId -Force
    Write-Host "Bixi Seed 已停止。"
} else {
    Write-Host "Bixi Seed 当前未运行。"
}
if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
