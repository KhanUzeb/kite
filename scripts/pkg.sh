#!/usr/bin/env bash
# kite-release-version: 0.9.6
# Kite package maintenance (not part of `kite` CLI): update, reinstall, uninstall.
set -euo pipefail

ACTION=""
INSTALL_DIR=""
DEV_EXTRAS=1
REMOVE_VENV=0
NO_PULL=0

usage() {
  cat <<'EOF'
Usage: ./scripts/pkg.sh <update|reinstall|uninstall> [options]

Actions:
  update      git pull (if repo) + editable pip install
  reinstall   force reinstall kite in .venv
  uninstall   pip uninstall kite; optional --remove-venv

Options:
  --dir PATH       Repo root (default: parent of scripts/)
  --no-dev         Runtime deps only (omit pytest dev extra)
  --remove-venv    With uninstall: delete .venv after removing package
  --no-pull        With update: skip git pull
  -h, --help       Show this help

Examples:
  ./scripts/pkg.sh update
  ./scripts/pkg.sh reinstall
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

activate_venv() {
  local root="$1"
  if [[ ! -f "${root}/.venv/bin/activate" ]]; then
    echo "No .venv at ${root}. Run ./scripts/install.sh first." >&2
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
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --no-dev) DEV_EXTRAS=0; shift ;;
    --remove-venv) REMOVE_VENV=1; shift ;;
    --no-pull) NO_PULL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${INSTALL_DIR}" ]]; then
  INSTALL_DIR="$(repo_root_from_script)"
fi

if [[ ! -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  echo "No pyproject.toml in ${INSTALL_DIR}. Use --dir or run from a kite checkout." >&2
  exit 1
fi

ensure_uv

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
