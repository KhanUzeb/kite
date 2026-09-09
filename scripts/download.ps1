# kite-release-version: 0.9.6
# Windows bootstrap — fetch install.ps1 (raw) or fall back to shallow git clone.
#
#   irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.ps1 | iex
#
# If raw 404s (private repo), use:
#   git clone --depth 1 https://github.com/KhanUzeb/kite.git $env:TEMP\kite-get
#   & $env:TEMP\kite-get\scripts\install.ps1
#   Remove-Item -Recurse -Force $env:TEMP\kite-get
#
# Or skip scripts (uv + git):
#   irm https://astral.sh/uv/install.ps1 | iex
#   uv tool install --force "git+https://github.com/KhanUzeb/kite.git"
#   uv tool update-shell

$ErrorActionPreference = "Stop"

$RepoSlug = if ($env:KITE_REPO_SLUG) { $env:KITE_REPO_SLUG } else { "KhanUzeb/kite" }
$Branch = if ($env:KITE_BRANCH) { $env:KITE_BRANCH } else { "main" }
$RepoUrl = if ($env:KITE_REPO_URL) { $env:KITE_REPO_URL } else { "https://github.com/$RepoSlug.git" }
$RawBase = if ($env:KITE_RAW_BASE) { $env:KITE_RAW_BASE } else { "https://raw.githubusercontent.com/$RepoSlug/$Branch" }

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
        Write-Host "Raw download failed (private repo / 404). Falling back to git clone..." -ForegroundColor Yellow
        $repoDir = Join-Path $work "repo"
        git clone --depth 1 --branch $Branch $RepoUrl $repoDir
        if ($LASTEXITCODE -ne 0) { throw "git clone failed — sign in to GitHub or make the repo public" }
        Copy-Item (Join-Path $repoDir "scripts\install.ps1") $installPs1
    }

    # Forward common switches if this script was invoked as a file with args.
    # When used via irm|iex, args are not available — default global install.
    & $installPs1 @args
} finally {
    try { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue } catch { }
}
