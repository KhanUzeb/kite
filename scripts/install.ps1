# kite-release-version: 0.9.6
# Install Kite as a global CLI (default via irm|iex) or editable checkout (-Dev).
#
# Windows / PowerShell. If ExecutionPolicy blocks you, use:
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex"
# Or once per user:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
# End-user (any directory):
#   irm …/install.ps1 | iex
# Contributor:
#   .\scripts\install.ps1 -Dev
param(
    [string]$Dir = "",
    [string]$Repo = "https://github.com/KhanUzeb/kite.git",
    [string]$Ref = "main",
    [string]$Python = "3.12",
    [switch]$Global,
    [switch]$Dev,
    [switch]$NoClone,
    [switch]$NoDev,
    [switch]$Force,
    [switch]$Verify,
    [switch]$Setup
)

$ErrorActionPreference = "Stop"

# Capture once at script scope — inside functions $MyInvocation refers to the function.
$script:ScriptPath = $PSCommandPath
if (-not $script:ScriptPath) {
    $script:ScriptPath = $MyInvocation.MyCommand.Path
}
$script:IsEphemeral = (
    [string]::IsNullOrWhiteSpace($script:ScriptPath) -or
    ($script:ScriptPath -match '[\\/]Temp[\\/]|[\\/]tmp[\\/]|kite-install')
)

function Show-Usage {
    Write-Host @'
Usage: .\scripts\install.ps1 [options]

Default: install kite globally for this Windows user (uv tool).
Then kite works from any folder — no clone, no Activate.ps1.

If Windows blocks the script (ExecutionPolicy):
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex"
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

Options:
  -Global          Same as default (global CLI on PATH)
  -Dev             Contributor: editable CLI from a kite checkout (+ .venv for pytest)
  -Dir PATH        Checkout path for -Dev
  -Repo URL        Git remote (default: KhanUzeb/kite on GitHub)
  -Ref REF         Git branch/tag/commit for tool install (default: main)
  -Python VER      Python version for uv (default: 3.12)
  -NoClone         With -Dev: install from existing checkout only
  -NoDev           With -Dev: omit pytest extra in local .venv
  -Force           Reinstall / overwrite existing kite tool entry
  -Verify          Run pytest after -Dev install
  -Setup           Run kite setup after install (interactive console only)

Examples:
  irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex
  .\scripts\install.ps1 -Force
  .\scripts\install.ps1 -Dev
'@
}

function Test-EphemeralScript {
    return [bool]$script:IsEphemeral
}

function Get-RepoRootFromScript {
    if (Test-EphemeralScript) { return $null }
    if (-not $script:ScriptPath) { return $null }
    $scriptRoot = Split-Path -Parent $script:ScriptPath
    if (-not $scriptRoot) { return $null }
    try {
        return (Resolve-Path (Join-Path $scriptRoot "..")).Path
    } catch {
        return $null
    }
}

function Test-KiteCheckout {
    param([string]$Root)
    if (-not $Root) { return $false }
    $pyproject = Join-Path $Root "pyproject.toml"
    if (-not (Test-Path $pyproject)) { return $false }
    $text = Get-Content -Raw $pyproject
    return ($text -match 'name\s*=\s*"kite"')
}

function Get-GitToolSpec {
    $url = $Repo.TrimEnd('.git')
    return "git+$url.git@$Ref"
}

function Invoke-Preflight {
    if (-not $env:USERPROFILE -or -not (Test-Path $env:USERPROFILE)) {
        throw 'USERPROFILE must be set and exist.'
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "git is required (uv installs kite from GitHub)." -ForegroundColor Red
        Write-Host "Install Git for Windows: https://git-scm.com/download/win"
        Write-Host "Or: winget install --id Git.Git -e --source winget"
        throw 'git not found'
    }
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }
}

function Refresh-UvPath {
    foreach ($p in @(
            (Join-Path $env:USERPROFILE ".local\bin"),
            (Join-Path $env:USERPROFILE ".cargo\bin"),
            (Join-Path $env:LOCALAPPDATA "uv\bin"),
            (Join-Path $env:LOCALAPPDATA "Programs\uv")
        )) {
        if ($p -and (Test-Path $p) -and ($env:Path -notlike "*$p*")) {
            $env:Path = $p + ';' + $env:Path
        }
    }
}

function Ensure-Uv {
    Refresh-UvPath
    if (Get-Command uv -ErrorAction SilentlyContinue) { return }
    Write-Host "uv not found - installing via official installer..."
    try {
        irm https://astral.sh/uv/install.ps1 | iex
    } catch {
        Write-Host "uv installer failed. If ExecutionPolicy blocked it, run:" -ForegroundColor Yellow
        Write-Host '  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"'
        throw
    }
    Refresh-UvPath
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv install finished but uv is still not on PATH. Open a new shell and re-run.'
    }
}

function Add-UserPathPersist {
    param([string]$BinDir)
    if (-not $BinDir -or -not (Test-Path $BinDir)) { return }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    $parts = $userPath -split ';' | Where-Object { $_ -and $_.Trim() }
    $normalized = $BinDir.TrimEnd('\')
    $exists = $false
    foreach ($p in $parts) {
        if ($p.TrimEnd('\') -ieq $normalized) { $exists = $true; break }
    }
    if (-not $exists) {
        $newPath = if ($userPath) { "$BinDir;$userPath" } else { $BinDir }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "Added to user PATH (persists for new terminals): $BinDir"
    }
    if ($env:Path -notlike "*$BinDir*") {
        $env:Path = $BinDir + ';' + $env:Path
    }
}

function Ensure-ToolPath {
    $binDir = $null
    try {
        $binDir = (uv tool dir --bin).Trim()
    } catch { }
    if ($binDir) {
        Add-UserPathPersist -BinDir $binDir
    }
    # Also let uv patch PowerShell profile when possible
    try {
        uv tool update-shell | Out-Null
        Write-Host "Ensured uv tool bin is on PATH (restart shell if kite is not found)."
    } catch {
        if ($binDir) {
            Write-Host "If kite is missing after restart, add to PATH: $binDir"
        }
    }
}

function Bootstrap-KiteHome {
    param([string]$InstallRoot, [string]$HomeDir)
    New-Item -ItemType Directory -Path $HomeDir -Force | Out-Null
    $envExample = if ($InstallRoot) { Join-Path $InstallRoot ".env.example" } else { $null }
    $envTarget = Join-Path $HomeDir ".env"
    if ($envExample -and -not (Test-Path $envTarget) -and (Test-Path $envExample)) {
        Copy-Item $envExample $envTarget
        Write-Host "Created $envTarget (template) - run: kite setup"
    }
    try {
        python -c "from kite.config import ensure_home; ensure_home()"
    } catch { }
}

function Install-GlobalCli {
    Ensure-Uv
    $spec = Get-GitToolSpec
    Write-Host "Installing kite CLI globally from $spec..."
    Write-Host "(isolated tool env — not cloning into your current directory)"

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($Force) {
        uv tool install --python $Python --force $spec
        $rc = $LASTEXITCODE
    } else {
        uv tool install --python $Python $spec
        $rc = $LASTEXITCODE
        if ($rc -ne 0) {
            Write-Host "Retrying with -Force (kite may already be installed)..."
            uv tool install --python $Python --force $spec
            $rc = $LASTEXITCODE
        }
    }
    $ErrorActionPreference = $prevEap
    if ($rc -ne 0) {
        throw "uv tool install failed (exit $rc). Check git + network to GitHub."
    }
    Ensure-ToolPath

    $kiteHome = if ($env:KITE_HOME) { $env:KITE_HOME } else { Join-Path $env:USERPROFILE ".kite" }
    New-Item -ItemType Directory -Path $kiteHome -Force | Out-Null
    $env:KITE_HOME = $kiteHome
    try {
        $toolDir = (uv tool dir).Trim()
        $toolPy = Join-Path $toolDir "kite\Scripts\python.exe"
        if (Test-Path $toolPy) {
            & $toolPy -c "from kite.config import ensure_home; ensure_home()"
        }
    } catch { }

    $kiteVersion = ""
    try { $kiteVersion = (kite --version 2>$null).Trim() } catch { }
    if ($kiteVersion) {
        Write-Host "Installed $kiteVersion"
    } else {
        Write-Host "Warning: kite not on PATH in this shell yet. Open a new terminal." -ForegroundColor Yellow
        try {
            $bin = (uv tool dir --bin).Trim()
            Write-Host "Or: `$env:Path = '$bin;' + `$env:Path"
        } catch { }
    }

    if ($Setup -and [Console]::IsInputRedirected -eq $false) {
        Write-Host ""
        Write-Host "Starting kite setup (Ctrl+C to skip)..."
        try { kite setup } catch { }
    }

    Write-Host ""
    Write-Host "Kite is installed globally on this user account (uv tool)."
    Write-Host "Opening 'kite' works from any folder — no clone, no .venv activate."
    Write-Host "Kite home: $kiteHome"
    Write-Host ""
    Write-Host "  cd C:\path\to\any\project"
    Write-Host "  kite"
    Write-Host ""
    Write-Host "First run:  kite setup"
    Write-Host "Update:     uv tool upgrade kite"
    Write-Host "Uninstall:  uv tool uninstall kite"
    Write-Host "Dev only:   .\scripts\install.ps1 -Dev"
}

function Install-DevEditable {
    $installRoot = $Dir
    if (-not $installRoot) {
        $fromScript = Get-RepoRootFromScript
        if ($fromScript -and (Test-KiteCheckout $fromScript)) {
            $installRoot = $fromScript
            $script:NoClone = $true
        } else {
            $installRoot = Join-Path $env:USERPROFILE "kite"
        }
    }

    $parent = Split-Path -Parent $installRoot
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if (-not $NoClone) {
        if (Test-Path (Join-Path $installRoot ".git")) {
            Write-Host "Repo already exists at $installRoot - pulling latest..."
            git -C $installRoot pull --ff-only
        } else {
            Write-Host "Cloning $Repo -> $installRoot (dev checkout)"
            git clone $Repo $installRoot
        }
    }

    if (-not (Test-KiteCheckout $installRoot)) {
        throw "No kite pyproject.toml in $installRoot. Use -Dir or run from a kite checkout."
    }

    Ensure-Uv
    Set-Location $installRoot

    # Editable CLI on PATH — opening kite works anywhere; no Activate.ps1 needed.
    Write-Host "Installing editable kite CLI on PATH (uv tool --editable)..."
    uv tool install --python $Python --force --editable $installRoot
    if ($LASTEXITCODE -ne 0) { throw "uv tool install --editable failed" }
    Ensure-ToolPath

    Write-Host "Creating contributor .venv for pytest only (optional)..."
    if (-not (Test-Path (Join-Path $installRoot ".venv"))) {
        uv venv --python $Python .venv
    }
    $venvPy = Join-Path $installRoot ".venv\Scripts\python.exe"
    if ($NoDev) {
        uv pip install --python $venvPy -e .
    } else {
        uv pip install --python $venvPy -e ".[dev]"
    }

    $kiteHome = if ($env:KITE_HOME) { $env:KITE_HOME } else { Join-Path $env:USERPROFILE ".kite" }
    New-Item -ItemType Directory -Path $kiteHome -Force | Out-Null
    $env:KITE_HOME = $kiteHome
    Bootstrap-KiteHome -InstallRoot $installRoot -HomeDir $kiteHome

    $kiteVersion = ""
    try { $kiteVersion = (kite --version 2>$null).Trim() } catch { }
    if ($kiteVersion) {
        Write-Host "Installed $kiteVersion (editable on PATH — works from any folder)"
    } else {
        Write-Host "Warning: kite not on PATH in this shell yet. Open a new terminal." -ForegroundColor Yellow
    }

    if ($Verify) {
        Write-Host "Running pytest (smoke check)..."
        $pytest = Join-Path $installRoot ".venv\Scripts\pytest.exe"
        if (Test-Path $pytest) { & $pytest -q } else { uv run --python $venvPy pytest -q }
    }

    if ($Setup -and [Console]::IsInputRedirected -eq $false) {
        Write-Host ""
        Write-Host "Starting kite setup (Ctrl+C to skip)..."
        try { kite setup } catch { }
    }

    Write-Host ""
    Write-Host "Dev checkout: $installRoot"
    Write-Host "Kite home:    $kiteHome"
    Write-Host ""
    Write-Host "Opening 'kite' uses this editable install from any directory."
    Write-Host "Local .venv is only for pytest/IDE — do not activate it to run kite."
    Write-Host "Package: .\scripts\pkg.ps1 update | reinstall | uninstall"
}

try {
    Invoke-Preflight
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# Default is always global CLI on PATH (works anywhere on this user account).
# Contributors must pass -Dev explicitly.
$useDev = ($Dev -or $NoClone -or $Verify) -and (-not $Global)

if ($useDev) {
    Install-DevEditable
} else {
    Install-GlobalCli
}
