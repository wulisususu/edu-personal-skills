# Thin Windows PowerShell launcher. All refresh logic lives in refresh.py.
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RefreshPy = Join-Path $ScriptDir "refresh.py"

if ($env:PYTHON) {
    & $env:PYTHON $RefreshPy @args
    exit $LASTEXITCODE
}

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PyLauncher) {
    & py -3 $RefreshPy @args
    exit $LASTEXITCODE
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($Python) {
    & python $RefreshPy @args
    exit $LASTEXITCODE
}

Write-Error "Python 3 was not found. Set the PYTHON environment variable or install Python 3."
exit 1
