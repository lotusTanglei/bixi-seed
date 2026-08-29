$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
Set-Location $ProjectRoot
Assert-PythonEnvironment
Assert-Configuration
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$existing = Get-ManagedProcess $PidFile
if ($existing) {
    Write-Host "Bixi Seed 已经在运行，PID=$($existing.ProcessId)。"
    exit 0
}
if (Test-Path $PidFile) { Remove-Item $PidFile -Force }

Test-PortAvailable

& $VenvPython manage.py check
if ($LASTEXITCODE -ne 0) { throw "Django 配置检查失败，服务未启动。" }
& $VenvPython manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败，服务未启动。" }

$port = Get-ConfiguredPort
$bindHost = Get-ConfiguredBindHost
$stdout = Join-Path $LogDirectory "server.out.log"
$stderr = Join-Path $LogDirectory "server.err.log"
$arguments = @(
    "-m", "uvicorn", "config.asgi:application",
    "--host", $bindHost,
    "--port", "$port",
    "--no-access-log"
)
$process = Start-Process -FilePath $VenvPython -ArgumentList $arguments -WorkingDirectory $ProjectRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
$process.Id | Set-Content -Path $PidFile -Encoding ascii

$healthy = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        if (Test-Health) { $healthy = $true; break }
    } catch { }
}
if (-not $healthy) {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    throw "服务启动后健康检查未通过，请运行 logs.bat 查看日志。"
}
Write-Host "Bixi Seed 已在后台启动，地址: http://127.0.0.1:$port"
