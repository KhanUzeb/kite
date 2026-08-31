# Install Kite on Windows: clone (optional), venv, editable install, env bootstrap.
param(
    [string]$Dir = "",
    [string]$Repo = "https://github.com/KhanUzeb/kite.git",
    [string]$Python = "3.12",
    [switch]$NoClone,
    [switch]$NoDev,
    [switch]$Setup
)

$ErrorActionPreference = "Stop"

function Show-Usage {
    Write-Host @'
Usage: .\scripts\install.ps1 [options]

Options:
  -Dir PATH        Install directory (default: current repo or %USERPROFILE%\kite)
  -Repo URL        Git remote to clone (default: KhanUzeb/kite on GitHub)
  -Python VER      Python version for uv venv (default: 3.12)
  -NoClone         Skip git clone; install from the current directory
  -NoDev           Install runtime deps only (omit pytest dev extra)
  -Setup           Run kite setup after install (interactive console only)

Examples:
  git clone https://github.com/KhanUzeb/kite.git; cd kite; .\scripts\install.ps1
  irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex
  .\scripts\install.ps1 -Dir C:\tools\kite
'@
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { return }
    Write-Host "uv not found - installing via official installer..."
    irm https://astral.sh/uv/install.ps1 | iex
    $uvBin = Join-Path $env:USERPROFILE ".local\bin"
    if (Test-Path $uvBin) {
        $env:Path = $uvBin + ';' + $env:Path
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv install finished but uv is still not on PATH. Open a new shell and re-run.'
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoFromScript = Resolve-Path (Join-Path $scriptRoot "..")

if (-not $Dir) {
    if ($NoClone -or (Test-Path (Join-Path $repoFromScript "pyproject.toml"))) {
        $Dir = $repoFromScript
        $NoClone = $true
    } else {
        $Dir = Join-Path $env:USERPROFILE "kite"
    }
}

$parent = Split-Path -Parent $Dir
if ($parent -and -not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

if (-not $NoClone) {
    if (Test-Path (Join-Path $Dir ".git")) {
        Write-Host "Repo already exists at $Dir - pulling latest..."
        git -C $Dir pull --ff-only
    } else {
        Write-Host "Cloning $Repo -> $Dir"
        git clone $Repo $Dir
    }
}

if (-not (Test-Path (Join-Path $Dir "pyproject.toml"))) {
    throw "No pyproject.toml in $Dir. Use -Dir or run from a kite checkout."
}

Ensure-Uv
Set-Location $Dir

Write-Host "Creating venv (.venv) with Python $Python..."
if (Test-Path (Join-Path $Dir ".venv")) {
    Write-Host "Using existing .venv"
} else {
    uv venv --python $Python .venv
}

$activate = Join-Path $Dir ".venv\Scripts\Activate.ps1"
. $activate

if ($NoDev) {
    uv pip install -e .
} else {
    uv pip install -e ".[dev]"
}

$kiteHome = if ($env:KITE_HOME) { $env:KITE_HOME } else { Join-Path $env:USERPROFILE ".kite" }
New-Item -ItemType Directory -Path $kiteHome -Force | Out-Null
$envExample = Join-Path $Dir ".env.example"
$envTarget = Join-Path $kiteHome ".env"
if (-not (Test-Path $envTarget) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envTarget
    Write-Host "Created $envTarget (template) - run: kite setup"
}
python -c "from kite.config import ensure_home; ensure_home()" 2>$null

if ($Setup -and [Console]::IsInputRedirected -eq $false) {
    Write-Host ""
    Write-Host "Starting kite setup (Ctrl+C to skip)..."
    try { kite setup } catch { }
}

$venvScripts = Join-Path $Dir ".venv\Scripts"
$readme = Join-Path $Dir "README.md"
Write-Host ""
Write-Host "Kite installed in: $Dir"
Write-Host ""
Write-Host "Activate this shell:"
Write-Host "  . `"$activate`""
Write-Host ""
Write-Host "Use kite from any project directory (workspace = current directory):"
Write-Host "  cd C:\path\to\your\project"
Write-Host "  kite"
Write-Host '  kite run "summarize this repo"'
Write-Host "  kite chat --cwd C:\path\to\other\project"
Write-Host ""
Write-Host "Or target a directory explicitly:"
Write-Host '  kite run --cwd C:\path\to\project "add tests"'
Write-Host ""
Write-Host "Make kite available in every new PowerShell session (add to `$PROFILE):"
Write-Host "  `$env:Path = `"$venvScripts;`" + `$env:Path"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  kite setup                 # guided API key + model picker"
Write-Host "  kite providers"
Write-Host "  kite models -p groq --select"
Write-Host "  kite runtime-config"
Write-Host ""
Write-Host "Docs: $readme"
