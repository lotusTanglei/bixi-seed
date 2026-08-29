$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:VenvPython = Join-Path $script:ProjectRoot ".venv\Scripts\python.exe"
$script:EnvPath = Join-Path $script:ProjectRoot ".env"
$script:DataDirectory = [Environment]::GetEnvironmentVariable("BIXI_DATA_DIR")
if ((-not $script:DataDirectory) -and (Test-Path $script:EnvPath)) {
    $dataLine = Get-Content $script:EnvPath | Where-Object { $_ -match "^\s*BIXI_DATA_DIR\s*=" } | Select-Object -First 1
    if ($dataLine -match "^\s*BIXI_DATA_DIR\s*=\s*(.+?)\s*$") { $script:DataDirectory = $Matches[1].Trim('"', "'") }
}
if (-not $script:DataDirectory) { $script:DataDirectory = Join-Path $script:ProjectRoot "data" }
if (-not [IO.Path]::IsPathRooted($script:DataDirectory)) { $script:DataDirectory = Join-Path $script:ProjectRoot $script:DataDirectory }
$script:PidFile = Join-Path $script:DataDirectory "bixi-seed.pid"
$script:DevPidFile = Join-Path $script:ProjectRoot "data\bixi-seed-dev.pid"
$script:LogDirectory = Join-Path $script:DataDirectory "logs"

function Assert-PythonEnvironment {
    if (-not (Test-Path $script:VenvPython)) {
        throw "Python 虚拟环境不存在，请先运行 setup.bat。"
    }
}

function Assert-Configuration {
    if (-not (Test-Path $script:EnvPath)) { throw "配置文件 .env 不存在，请先运行 setup.bat。" }
    $secret = [Environment]::GetEnvironmentVariable("BIXI_SECRET_KEY")
    if (-not $secret) {
        $secretLine = Get-Content $script:EnvPath | Where-Object { $_ -match "^\s*BIXI_SECRET_KEY\s*=" } | Select-Object -First 1
        if ($secretLine -match "^\s*BIXI_SECRET_KEY\s*=\s*(.+?)\s*$") { $secret = $Matches[1].Trim('"', "'") }
    }
    if (-not $secret -or $secret -in @("generate-during-setup", "development-only-change-this-secret")) {
        throw "Django Secret Key 尚未配置，请先运行 setup.bat。"
    }
    $port = Get-ConfiguredPort
    if ($port -lt 1 -or $port -gt 65535) { throw "BIXI_PORT 必须是 1 到 65535 之间的数字。" }
}

function Test-PortAvailable {
    & $script:VenvPython manage.py check_port --host (Get-ConfiguredBindHost) --port (Get-ConfiguredPort)
    if ($LASTEXITCODE -ne 0) { throw "服务端口不可用，服务未启动。" }
}

function Test-Health {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$(Get-ConfiguredPort)/api/health/" -UseBasicParsing -TimeoutSec 2
        $payload = $response.Content | ConvertFrom-Json
        return $payload.status -eq "ok" -and $payload.service -eq "bixi-seed-core"
    } catch { return $false }
}

function Get-ConfiguredPort {
    $port = [Environment]::GetEnvironmentVariable("BIXI_PORT")
    $envFile = Join-Path $script:ProjectRoot ".env"
    if ((-not $port) -and (Test-Path $envFile)) {
        $line = Get-Content $envFile | Where-Object { $_ -match "^\s*BIXI_PORT\s*=" } | Select-Object -First 1
        if ($line -match "^\s*BIXI_PORT\s*=\s*(.+?)\s*$") { $port = $Matches[1].Trim('"', "'") }
    }
    if ($port -match "^[0-9]+$") { return [int]$port }
    if ($port) { return 0 }
    return 8000
}

function Get-ConfiguredBindHost {
    $bindHost = [Environment]::GetEnvironmentVariable("BIXI_BIND_HOST")
    $envFile = Join-Path $script:ProjectRoot ".env"
    if ((-not $bindHost) -and (Test-Path $envFile)) {
        $line = Get-Content $envFile | Where-Object { $_ -match "^\s*BIXI_BIND_HOST\s*=" } | Select-Object -First 1
        if ($line -match "^\s*BIXI_BIND_HOST\s*=\s*(.+?)\s*$") { $bindHost = $Matches[1] }
    }
    if ($bindHost) { return $bindHost.Trim('"', "'") }
    return "127.0.0.1"
}

function Get-ManagedProcess([string]$PidPath) {
    if (-not (Test-Path $PidPath)) { return $null }
    $rawPid = (Get-Content $PidPath -Raw).Trim()
    if ($rawPid -notmatch "^[0-9]+$") { return $null }
    $managed = Get-CimInstance Win32_Process -Filter "ProcessId = $rawPid" -ErrorAction SilentlyContinue
    if ($null -eq $managed) { return $null }
    if ($managed.CommandLine -notmatch "uvicorn" -or $managed.CommandLine -notmatch "config\.asgi:application") {
        return $null
    }
    return $managed
}
