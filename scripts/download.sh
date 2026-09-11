#!/usr/bin/env bash
# kite-release-version: 0.9.7
# Cross-platform Unix bootstrap (macOS + Ubuntu/Linux + WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash
#
# Prefers raw download of install.sh; if that 404s (private repo / CDN), falls back
# to a shallow git clone. Does not leave a clone in your project directory.
set -euo pipefail

REPO_SLUG="${KITE_REPO_SLUG:-KhanUzeb/kite}"
BRANCH="${KITE_BRANCH:-main}"
REPO_URL="${KITE_REPO_URL:-https://github.com/${REPO_SLUG}.git}"
RAW_BASE="${KITE_RAW_BASE:-https://raw.githubusercontent.com/${REPO_SLUG}/${BRANCH}}"

usage() {
  cat <<EOF
Usage: download.sh [install.sh options]

Unix bootstrap for macOS and Linux. Fetches install.sh and runs a global CLI install.

One-liner (repo must be public for raw.githubusercontent.com):
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash -s -- --setup

If the repo is private, use git (your credentials) instead:
  git clone --depth 1 ${REPO_URL} /tmp/kite-get && bash /tmp/kite-get/scripts/install.sh && rm -rf /tmp/kite-get

Or skip scripts entirely (needs uv + git):
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv tool install --force "git+${REPO_URL%@*}@${BRANCH}"
  uv tool update-shell

Windows (PowerShell):
  irm ${RAW_BASE}/scripts/install.ps1 | iex
EOF
}

if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

uname_s="$(uname -s 2>/dev/null || echo unknown)"
case "${uname_s}" in
  Darwin*|Linux*) ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "On Windows use PowerShell:" >&2
    echo "  irm ${RAW_BASE}/scripts/install.ps1 | iex" >&2
    exit 1
    ;;
  *)
    echo "Unsupported OS (${uname_s}). See README." >&2
    exit 1
    ;;
esac

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "'$1' is required but not found." >&2
    case "${uname_s}" in
      Darwin*) echo "  xcode-select --install" >&2 ;;
      Linux*)
        if command -v apt-get >/dev/null 2>&1; then
          echo "  sudo apt-get update && sudo apt-get install -y curl git ca-certificates" >&2
        fi
        ;;
    esac
    exit 1
  fi
}

need curl
need git

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/kite-bootstrap.XXXXXX")"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

INSTALL_SH="${WORKDIR}/install.sh"
RAW_URL="${RAW_BASE}/scripts/install.sh"

echo "Fetching install.sh (${BRANCH})..."
if curl -fsSL "${RAW_URL}" -o "${INSTALL_SH}"; then
  :
else
  echo "Raw download failed (HTTP error / private repo). Falling back to git clone..." >&2
  git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${WORKDIR}/repo"
  cp "${WORKDIR}/repo/scripts/install.sh" "${INSTALL_SH}"
fi

if command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "${INSTALL_SH}" 2>/dev/null || true
fi
if command -v tr >/dev/null 2>&1 && grep -q $'\r' "${INSTALL_SH}" 2>/dev/null; then
  tr -d '\r' < "${INSTALL_SH}" > "${INSTALL_SH}.lf"
  mv "${INSTALL_SH}.lf" "${INSTALL_SH}"
fi
chmod +x "${INSTALL_SH}"
exec bash "${INSTALL_SH}" "$@"
