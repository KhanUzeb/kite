#!/usr/bin/env bash
# kite-release-version: 0.9.6
# Kite package maintenance (not part of `kite` CLI): update, reinstall, uninstall.
# Supports global `uv tool` installs and contributor editable .venv checkouts.
set -euo pipefail

ACTION=""
INSTALL_DIR=""
DEV_EXTRAS=1
REMOVE_VENV=0
NO_PULL=0
GLOBAL=0

usage() {
  cat <<'EOF'
Usage: ./scripts/pkg.sh <update|reinstall|uninstall> [options]

Actions:
  update      Upgrade global kite tool, or git pull + editable reinstall
  reinstall   Force reinstall (tool or .venv)
  uninstall   Remove kite (uv tool uninstall, or pip uninstall)

Options:
  --global         Operate on uv tool install (default when kite is a uv tool)
  --dir PATH       Repo root for editable mode (default: parent of scripts/)
  --no-dev         Runtime deps only (omit pytest dev extra; editable only)
  --remove-venv    With uninstall (editable): delete .venv after removing package
  --no-pull        With update (editable): skip git pull
  -h, --help       Show this help

Examples:
  ./scripts/pkg.sh update
  ./scripts/pkg.sh update --global
  ./scripts/pkg.sh uninstall --global
  ./scripts/pkg.sh uninstall --remove-venv
EOF
}

repo_root_from_script() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/.." && pwd
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi
  echo "uv not found. Run ./scripts/install.sh first or install uv: https://docs.astral.sh/uv/" >&2
  exit 1
}

is_uv_tool_kite() {
  uv tool list 2>/dev/null | grep -qiE '^kite([[:space:]]|$)' || return 1
}

activate_venv() {
  local root="$1"
  if [[ ! -f "${root}/.venv/bin/activate" ]]; then
    echo "No .venv at ${root}. Run ./scripts/install.sh --dev first." >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  source "${root}/.venv/bin/activate"
}

install_editable() {
  local root="$1"
  cd "${root}"
  if [[ "${DEV_EXTRAS}" -eq 1 ]]; then
    uv pip install -e ".[dev]"
  else
    uv pip install -e .
  fi
}

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 2
fi

case "$1" in
  update|reinstall|uninstall) ACTION="$1"; shift ;;
  -h|--help) usage; exit 0 ;;
  *) echo "Unknown action: $1" >&2; usage >&2; exit 2 ;;
esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --global) GLOBAL=1; shift ;;
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --no-dev) DEV_EXTRAS=0; shift ;;
    --remove-venv) REMOVE_VENV=1; shift ;;
    --no-pull) NO_PULL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ensure_uv

if [[ "${GLOBAL}" -eq 0 ]] && [[ -z "${INSTALL_DIR}" ]]; then
  if is_uv_tool_kite; then
    GLOBAL=1
  fi
fi

if [[ "${GLOBAL}" -eq 1 ]]; then
  case "${ACTION}" in
    update)
      echo "Upgrading kite (uv tool)..."
      uv tool upgrade kite || uv tool install --force "git+https://github.com/KhanUzeb/kite.git"
      kite --version 2>/dev/null || true
      ;;
    reinstall)
      echo "Reinstalling kite (uv tool)..."
      uv tool install --force "git+https://github.com/KhanUzeb/kite.git"
      kite --version 2>/dev/null || true
      ;;
    uninstall)
      echo "Uninstalling kite (uv tool)..."
      uv tool uninstall kite
      echo "Done. ~/.kite/ config and sessions were not removed."
      ;;
  esac
  exit 0
fi

if [[ -z "${INSTALL_DIR}" ]]; then
  INSTALL_DIR="$(repo_root_from_script)"
fi

if [[ ! -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  echo "No pyproject.toml in ${INSTALL_DIR}. Use --dir, --global, or run from a kite checkout." >&2
  exit 1
fi

case "${ACTION}" in
  update)
    if [[ "${NO_PULL}" -eq 0 ]] && [[ -d "${INSTALL_DIR}/.git" ]]; then
      echo "Pulling latest from origin..."
      git -C "${INSTALL_DIR}" pull --ff-only
    fi
    activate_venv "${INSTALL_DIR}"
    echo "Updating kite (editable install)..."
    install_editable "${INSTALL_DIR}"
    if KITE_VERSION="$(kite --version 2>/dev/null || true)"; [[ -n "${KITE_VERSION}" ]]; then
      echo "kite ${KITE_VERSION}"
    else
      echo "Updated. Activate .venv to use kite."
    fi
    ;;
  reinstall)
    activate_venv "${INSTALL_DIR}"
    echo "Reinstalling kite..."
    cd "${INSTALL_DIR}"
    if [[ "${DEV_EXTRAS}" -eq 1 ]]; then
      uv pip install --reinstall -e ".[dev]"
    else
      uv pip install --reinstall -e .
    fi
    if KITE_VERSION="$(kite --version 2>/dev/null || true)"; [[ -n "${KITE_VERSION}" ]]; then
      echo "kite ${KITE_VERSION}"
    else
      echo "Reinstalled. Activate .venv to use kite."
    fi
    ;;
  uninstall)
    activate_venv "${INSTALL_DIR}"
    echo "Uninstalling kite package..."
    uv pip uninstall kite -y
    if [[ "${REMOVE_VENV}" -eq 1 ]]; then
      echo "Removing ${INSTALL_DIR}/.venv"
      rm -rf "${INSTALL_DIR}/.venv"
    else
      echo "Tip: --remove-venv deletes .venv as well."
    fi
    echo "Done. ~/.kite/ config and sessions were not removed."
    ;;
esac
