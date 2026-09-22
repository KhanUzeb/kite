# kite-release-version: 1.0.1
# Windows bootstrap - fetch install.ps1 (raw) or fall back to shallow git clone.
#
#   irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.ps1 | iex
#
# Installs via `uv tool install git+https://github.com/...` only (not PyPI).
#
# If ExecutionPolicy blocks scripts:
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.ps1 | iex"
#
# With install.ps1 switches (run from a saved copy, not irm|iex):
#   .\scripts\download.ps1 -Force
#   .\scripts\download.ps1 -Setup

$ErrorActionPreference = "Stop"

$RepoSlug = if ($env:KITE_REPO_SLUG) { $env:KITE_REPO_SLUG } else { "KhanUzeb/kite" }
$Branch = if ($env:KITE_BRANCH) { $env:KITE_BRANCH } else { "main" }
$RepoUrl = if ($env:KITE_REPO_URL) { $env:KITE_REPO_URL } else { "https://github.com/$RepoSlug.git" }
$RawBase = if ($env:KITE_RAW_BASE) { $env:KITE_RAW_BASE } else { "https://raw.githubusercontent.com/$RepoSlug/$Branch" }

function Get-GitToolSpec {
    $url = $RepoUrl
    if ($url.EndsWith('.git')) { $url = $url.Substring(0, $url.Length - 4) }
    return "git+$url.git@$Branch"
}

function Show-DownloadUsage {
    Write-Host @"
Usage: download.ps1 [install.ps1 options]

Windows bootstrap. Fetches install.ps1 and runs a global CLI install via uv tool
from GitHub (not PyPI).

One-liner (public repo only for raw.githubusercontent.com):
  irm $RawBase/scripts/download.ps1 | iex

If ExecutionPolicy blocks you:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm $RawBase/scripts/download.ps1 | iex"

Pass switches when running a local copy (same as install.ps1):
  .\scripts\download.ps1 -Force
  .\scripts\download.ps1 -Setup

Environment overrides:
  KITE_REPO_SLUG, KITE_BRANCH, KITE_REPO_URL, KITE_RAW_BASE

Private repo (raw 404) — git clone then install:
  git clone --depth 1 --branch $Branch $RepoUrl `$env:TEMP\kite-get
  & `$env:TEMP\kite-get\scripts\install.ps1
  Remove-Item -Recurse -Force `$env:TEMP\kite-get

Or uv + git only:
  irm https://astral.sh/uv/install.ps1 | iex
  uv tool install --python 3.12 --force "$(Get-GitToolSpec)"
  uv tool update-shell
"@
}

function Write-PrivateRepoFallback {
    Write-Host ""
    Write-Host "Raw download failed (HTTP 404 or private repo)." -ForegroundColor Yellow
    Write-Host "Option A — shallow clone, then install:"
    Write-Host "  git clone --depth 1 --branch $Branch $RepoUrl `$env:TEMP\kite-get"
    Write-Host "  & `$env:TEMP\kite-get\scripts\install.ps1"
    Write-Host "  Remove-Item -Recurse -Force `$env:TEMP\kite-get"
    Write-Host ""
    Write-Host "Option B — uv + git only:"
    Write-Host "  irm https://astral.sh/uv/install.ps1 | iex"
    Write-Host "  uv tool install --python 3.12 --force `"$(Get-GitToolSpec)`""
    Write-Host "  uv tool update-shell"
    Write-Host ""
    Write-Host "Override: `$env:KITE_REPO_SLUG, `$env:KITE_BRANCH, `$env:KITE_REPO_URL"
}

if ($args -contains "-Help" -or $args -contains "-h" -or $args -contains "--help") {
    Show-DownloadUsage
    exit 0
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git is required. Install: https://git-scm.com/download/win" -ForegroundColor Red
    throw "git not found"
}

$work = Join-Path $env:TEMP ("kite-bootstrap-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work -Force | Out-Null
$installPs1 = Join-Path $work "install.ps1"
$rawUrl = "$RawBase/scripts/install.ps1"

try {
    Write-Host "Fetching install.ps1 ($Branch)..."
    try {
        Invoke-WebRequest -Uri $rawUrl -OutFile $installPs1 -UseBasicParsing
    } catch {
        Write-Host "Raw download failed for $rawUrl" -ForegroundColor Yellow
        Write-PrivateRepoFallback
        Write-Host "Attempting git clone fallback..." -ForegroundColor Yellow
        $repoDir = Join-Path $work "repo"
        git clone --depth 1 --branch $Branch $RepoUrl $repoDir
        if ($LASTEXITCODE -ne 0) {
            throw "git clone failed - sign in to GitHub or check KITE_REPO_URL / KITE_BRANCH"
        }
        Copy-Item (Join-Path $repoDir "scripts\install.ps1") $installPs1
    }

    # Forward switches to install.ps1 (local file only; irm|iex has no args).
    & $installPs1 @args

    $kiteVersion = ""
    try { $kiteVersion = (kite --version 2>$null).Trim() } catch { }
    if ($kiteVersion) {
        Write-Host ""
        Write-Host "kite on PATH: $kiteVersion"
    }
} finally {
    try { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue } catch { }
}
