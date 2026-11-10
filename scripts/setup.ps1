$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
Set-Location $ProjectRoot

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
    Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $ProjectRoot ".env")
    Write-Host "已创建 .env，请按需修改配置。"
}

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    & py -3 -m venv (Join-Path $ProjectRoot ".venv")
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw "未找到 Python 3，请先安装 Python 3.12 或更高版本。" }
    & python -m venv (Join-Path $ProjectRoot ".venv")
}
$pythonVersion = if ($pythonLauncher) { & py -3 -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" } else { & python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" }
if ([version]$pythonVersion -lt [version]"3.12") { throw "Python 版本过低，请安装 Python 3.12 或更高版本。" }
Assert-PythonEnvironment
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")

$envPath = Join-Path $ProjectRoot ".env"
$envContent = Get-Content $envPath -Raw
if ($envContent -match "generate-during-setup|replace-this-with-a-long-random-value") {
    $generatedSecret = (& $VenvPython -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
    $envContent = $envContent -replace "generate-during-setup|replace-this-with-a-long-random-value", $generatedSecret
    Set-Content -Path $envPath -Value $envContent -Encoding utf8
    Write-Host "已为当前环境生成 Django Secret Key。"
}

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) { throw "未找到 npm，请先安装 Node.js LTS。" }
Push-Location (Join-Path $ProjectRoot "frontend")
try {
    & npm install
    & npm run build
} finally {
    Pop-Location
}

& $VenvPython manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败。" }
& $VenvPython manage.py collectstatic --noinput
if ($LASTEXITCODE -ne 0) { throw "静态文件收集失败。" }
Write-Host "基础环境已经准备完成。"
if ($env:BIXI_SKIP_ADMIN_PROMPT) {
    Write-Host "BIXI_SKIP_ADMIN_PROMPT 已设置，跳过管理员创建；之后可运行 bootstrap_admin。"
} else {
    $adminUsername = Read-Host "管理员账号（直接回车跳过）"
    if ($adminUsername) {
        $securePassword = Read-Host "管理员密码（至少 10 个字符）" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        $adminContact = Read-Host "管理员联系方式（手机号、微信号等）"
        $env:BIXI_ADMIN_USERNAME = $adminUsername
        $env:BIXI_ADMIN_PASSWORD = $adminPassword
        $env:BIXI_ADMIN_CONTACT = $adminContact
        & $VenvPython manage.py bootstrap_admin
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        Remove-Item Env:BIXI_ADMIN_USERNAME -ErrorAction SilentlyContinue
        Remove-Item Env:BIXI_ADMIN_PASSWORD -ErrorAction SilentlyContinue
        Remove-Item Env:BIXI_ADMIN_CONTACT -ErrorAction SilentlyContinue
    }
}
}
Write-Host "可以运行 start.bat 启动服务。"
