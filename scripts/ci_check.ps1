# kite-release-version: 0.9.8.5
# Same gates as .github/workflows/tests.yml — run before push to main.
# Usage: .\scripts\ci_check.ps1 [-Release]  # -Release adds RELEASE doc + CHANGELOG check
param([switch]$Release)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $env:KITE_SKIP_SETUP) { $env:KITE_SKIP_SETUP = "1" }
if (-not $env:KITE_TYPED_PICK) { $env:KITE_TYPED_PICK = "1" }
if (-not $env:KITE_HOME) {
    $env:KITE_HOME = Join-Path $env:TEMP "kite-ci-home"
    New-Item -ItemType Directory -Force -Path $env:KITE_HOME | Out-Null
}
function Resolve-CiPython {
    param([string]$Root)
    if ($env:PYTHON) { return $env:PYTHON }
    foreach ($candidate in @(
            (Join-Path $Root ".venv\Scripts\python.exe"),
            (Join-Path $Root ".venv/bin/python")
        )) {
        if (Test-Path $candidate) { return $candidate }
    }
    foreach ($name in @("python", "py", "python3")) {
        if (Get-Command $name -ErrorAction SilentlyContinue) { return $name }
    }
    throw "No Python found. Run .\scripts\install.ps1 -Dev or set PYTHON."
}
$Python = Resolve-CiPython -Root $Root
Write-Host "Using Python: $Python"
Write-Host "== sync_version --check"
if ($Release) { & $Python scripts/sync_version.py --check --release }
else { & $Python scripts/sync_version.py --check }
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "== ruff"
& $Python -m ruff check src tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "== pytest"
& $Python -m pytest -q --tb=short -p faulthandler
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "== kite bench --check"
& $Python -m kite.cli.run bench --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "CI gates ok"
