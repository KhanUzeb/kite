# kite-release-version: 0.9.6
# Kite package maintenance (not part of `kite` CLI): update, reinstall, uninstall.
# Supports global `uv tool` installs and contributor editable .venv checkouts.
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("update", "reinstall", "uninstall")]
    [string]$Action,

    [string]$Dir = "",
    [switch]$Global,
    [switch]$NoDev,
    [switch]$RemoveVenv,
    [switch]$NoPull
)

$ErrorActionPreference = "Stop"

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { return }
    throw "uv not found. Run .\scripts\install.ps1 first or install uv: https://docs.astral.sh/uv/"
}

function Test-UvToolKite {
    try {
        $list = uv tool list 2>$null | Out-String
        return ($list -match '(?m)^kite(\s|$)')
    } catch {
        return $false
    }
}

$scriptRoot = Split-Path -Parent $PSCommandPath
if (-not $scriptRoot) {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}

function Get-InstallRoot {
    param([string]$Override)
    if ($Override) { return (Resolve-Path $Override).Path }
    return (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

function Activate-Venv {
    param([string]$Root)
    $activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
    if (-not (Test-Path $activate)) {
        throw "No .venv at $Root. Run .\scripts\install.ps1 -Dev first."
    }
    . $activate
}

function Install-Editable {
    param([string]$Root, [bool]$Dev)
    Set-Location $Root
    if ($Dev) {
        uv pip install -e ".[dev]"
    } else {
        uv pip install -e .
    }
}

Ensure-Uv
$useGlobal = $Global
if (-not $useGlobal -and -not $Dir -and (Test-UvToolKite)) {
    $useGlobal = $true
}

if ($useGlobal) {
    switch ($Action) {
        "update" {
            Write-Host "Upgrading kite (uv tool)..."
            try {
                uv tool upgrade kite
            } catch {
                uv tool install --force "git+https://github.com/KhanUzeb/kite.git"
            }
            try { kite --version } catch { }
        }
        "reinstall" {
            Write-Host "Reinstalling kite (uv tool)..."
            uv tool install --force "git+https://github.com/KhanUzeb/kite.git"
            try { kite --version } catch { }
        }
        "uninstall" {
            Write-Host "Uninstalling kite (uv tool)..."
            uv tool uninstall kite
            Write-Host "Done. ~/.kite/ config and sessions were not removed."
        }
    }
    exit 0
}

$installRoot = Get-InstallRoot -Override $Dir
if (-not (Test-Path (Join-Path $installRoot "pyproject.toml"))) {
    throw "No pyproject.toml in $installRoot. Use -Dir, -Global, or run from a kite checkout."
}

$useDev = -not $NoDev

switch ($Action) {
    "update" {
        if (-not $NoPull -and (Test-Path (Join-Path $installRoot ".git"))) {
            Write-Host "Pulling latest from origin..."
            git -C $installRoot pull --ff-only
        }
        Activate-Venv -Root $installRoot
        Write-Host "Updating kite (editable install)..."
        Install-Editable -Root $installRoot -Dev $useDev
        $ver = (kite --version 2>$null).Trim()
        if ($ver) { Write-Host "kite $ver" } else { Write-Host "Updated. Activate .venv to use kite." }
    }
    "reinstall" {
        Activate-Venv -Root $installRoot
        Write-Host "Reinstalling kite..."
        Set-Location $installRoot
        if ($useDev) {
            uv pip install --reinstall -e ".[dev]"
        } else {
            uv pip install --reinstall -e .
        }
        $ver = (kite --version 2>$null).Trim()
        if ($ver) { Write-Host "kite $ver" } else { Write-Host "Reinstalled. Activate .venv to use kite." }
    }
    "uninstall" {
        Activate-Venv -Root $installRoot
        Write-Host "Uninstalling kite package..."
        uv pip uninstall kite -y
        if ($RemoveVenv) {
            $venv = Join-Path $installRoot ".venv"
            if (Test-Path $venv) {
                Write-Host "Removing $venv"
                Remove-Item -Recurse -Force $venv
            }
        } else {
            Write-Host "Tip: -RemoveVenv deletes .venv as well."
        }
        Write-Host "Done. ~/.kite/ config and sessions were not removed."
    }
}
