# todo-harvest Windows driver script (PowerShell)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"

# Check Python version
$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
if (-not $pyVersion) {
    Write-Error "python not found. Install Python 3.10+ and try again."
    exit 1
}
$major, $minor = $pyVersion -split '\.'
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 10)) {
    Write-Error "Python 3.10+ required, found $pyVersion"
    exit 1
}

# Bootstrap venv on first run
if (-not (Test-Path $VenvDir)) {
    Write-Host "First run - setting up virtual environment..."
    & python -m venv $VenvDir
    & "$VenvDir\Scripts\pip" install --quiet --upgrade pip
    & "$VenvDir\Scripts\pip" install --quiet -r "$ScriptDir\requirements.txt"
    & "$VenvDir\Scripts\pip" install --quiet -r "$ScriptDir\requirements-dev.txt"
    Write-Host "Setup complete.`n"
}

# Activate venv
& "$VenvDir\Scripts\Activate.ps1"

# Route --test to pytest
if ($args.Count -gt 0 -and $args[0] -eq "--test") {
    $testArgs = $args[1..($args.Count - 1)]
    & python -m pytest --cov=src --cov-report=term-missing @testArgs
    exit $LASTEXITCODE
}

# Delegate to main
& python -m src.main @args
exit $LASTEXITCODE
