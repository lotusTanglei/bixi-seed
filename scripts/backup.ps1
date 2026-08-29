$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
Set-Location $ProjectRoot
Assert-PythonEnvironment
& $VenvPython manage.py backup_data
