# kite-release-version: 0.9.3
# Kite package maintenance (not part of `kite` CLI): update, reinstall, uninstall.
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("update", "reinstall", "uninstall")]
    [string]$Action,

    [string]$Dir = "",
    [switch]$NoDev,
    [switch]$RemoveVenv,
    [switch]$NoPull
)

$ErrorActionPreference = "Stop"

function Show-Usage {
    Write-Host @'
Usage: .\scripts\pkg.ps1 <update|reinstall|uninstall> [options]

Actions:
  update      git pull (if repo) + editable pip install
  reinstall   force reinstall kite in .venv
  uninstall   pip uninstall kite; optional -RemoveVenv

Options:
  -Dir PATH       Repo root (default: parent of scripts/)
  -NoDev          Runtime deps only (omit pytest dev extra)
  -RemoveVenv     With uninstall: delete .venv after removing package
  -NoPull         With update: skip git pull

Examples:
  .\scripts\pkg.ps1 update
  .\scripts\pkg.ps1 reinstall
  .\scripts\pkg.ps1 uninstall -RemoveVenv
'@
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { return }
    throw "uv not found. Run .\scripts\install.ps1 first or install uv: https://docs.astral.sh/uv/"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-InstallRoot {
    param([string]$Override)
    if ($Override) { return (Resolve-Path $Override).Path }
    return (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

function Activate-Venv {
    param([string]$Root)
    $activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
    if (-not (Test-Path $activate)) {
        throw "No .venv at $Root. Run .\scripts\install.ps1 first."
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

$installRoot = Get-InstallRoot -Override $Dir
if (-not (Test-Path (Join-Path $installRoot "pyproject.toml"))) {
    throw "No pyproject.toml in $installRoot. Use -Dir or run from a kite checkout."
}

Ensure-Uv
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
