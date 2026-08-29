$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
Assert-Configuration
$port = Get-ConfiguredPort
$managed = Get-ManagedProcess $PidFile
if ($managed) {
    Write-Host "进程状态: 运行中 (PID=$($managed.ProcessId))"
    try {
        if (-not (Test-Health)) { throw "健康检查失败" }
        Write-Host "健康状态: 正常"
    } catch {
        Write-Host "健康状态: 不可用"
        exit 1
    }
} else {
    Write-Host "进程状态: 已停止"
    exit 1
}
