$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
Set-Location $ProjectRoot
Assert-PythonEnvironment
Assert-Configuration

$backend = Start-Process -FilePath $VenvPython -ArgumentList @(
    "-m", "uvicorn", "config.asgi:application", "--host", "127.0.0.1", "--port", "8000", "--reload"
) -WorkingDirectory $ProjectRoot -PassThru
try {
    Push-Location (Join-Path $ProjectRoot "frontend")
    & npm run dev
} finally {
    Pop-Location
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
