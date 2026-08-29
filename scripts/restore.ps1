$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
Set-Location $ProjectRoot
Assert-PythonEnvironment

if ($args.Count -ne 1) { throw "用法: restore.bat <备份文件路径>" }
$managed = Get-ManagedProcess $PidFile
if ($managed -or (Test-Health)) { throw "请先运行 stop.bat 停止服务，再执行恢复。" }

& $VenvPython manage.py restore_data --input $args[0]
& $VenvPython manage.py migrate --noinput
& "$PSScriptRoot\start.ps1"
