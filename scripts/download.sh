#!/usr/bin/env bash
# kite-release-version: 1.0.0
# Cross-platform Unix bootstrap (macOS + Ubuntu/Linux + WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash
#   curl -fsSL .../download.sh | bash -s -- --setup
#
# Installs via `uv tool install git+https://github.com/...` only (not PyPI).
# Prefers raw download of install.sh; if that 404s (private repo / CDN), falls back
# to a shallow git clone. Does not leave a clone in your project directory.
set -euo pipefail

REPO_SLUG="${KITE_REPO_SLUG:-KhanUzeb/kite}"
BRANCH="${KITE_BRANCH:-main}"
REPO_URL="${KITE_REPO_URL:-https://github.com/${REPO_SLUG}.git}"
RAW_BASE="${KITE_RAW_BASE:-https://raw.githubusercontent.com/${REPO_SLUG}/${BRANCH}}"

git_tool_spec() {
  local url="${REPO_URL%.git}"
  echo "git+${url}.git@${BRANCH}"
}

print_private_repo_fallback() {
  cat <<EOF >&2

Raw download failed (HTTP 404 or private repo — raw.githubusercontent.com only works for public repos).

Option A — shallow clone, then install (uses your git credentials):
  git clone --depth 1 --branch ${BRANCH} ${REPO_URL} /tmp/kite-get
  bash /tmp/kite-get/scripts/install.sh
  rm -rf /tmp/kite-get

Option B — uv + git only (no bootstrap scripts):
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv tool install --python 3.12 --force "$(git_tool_spec)"
  uv tool update-shell

Override repo/branch for any option:
  export KITE_REPO_SLUG=your-org/kite
  export KITE_BRANCH=main
  export KITE_REPO_URL=https://github.com/your-org/kite.git
EOF
}

usage() {
  cat <<EOF
Usage: download.sh [install.sh options]

Unix bootstrap for macOS and Linux. Fetches install.sh and runs a global CLI install
via \`uv tool install\` from GitHub (not PyPI).

One-liner (repo must be public for raw.githubusercontent.com):
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash -s -- --setup
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash -s -- -- --force

Pass-through to install.sh (local checkout):
  ./scripts/download.sh -- --force --setup

Environment overrides:
  KITE_REPO_SLUG   (default: ${REPO_SLUG})
  KITE_BRANCH      (default: ${BRANCH})
  KITE_REPO_URL    (default: ${REPO_URL})
  KITE_RAW_BASE    (default: ${RAW_BASE})

If the repo is private, see fallback commands printed on raw 404 (git clone or uv only).

Windows (PowerShell):
  irm ${RAW_BASE}/scripts/download.ps1 | iex
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm ${RAW_BASE}/scripts/download.ps1 | iex"
EOF
}

if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

# Allow `download.sh -- --force` (strip optional `--` before install.sh).
if [[ "${1:-}" == "--" ]]; then
  shift
fi

uname_s="$(uname -s 2>/dev/null || echo unknown)"
case "${uname_s}" in
  Darwin*|Linux*) ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "On Windows use PowerShell:" >&2
    echo "  irm ${RAW_BASE}/scripts/download.ps1 | iex" >&2
    echo "  powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm ${RAW_BASE}/scripts/download.ps1 | iex\"" >&2
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
  echo "Raw download failed for ${RAW_URL}" >&2
  print_private_repo_fallback
  echo "Attempting git clone fallback..." >&2
  if ! git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${WORKDIR}/repo"; then
    echo "git clone failed — sign in to GitHub or check KITE_REPO_URL / KITE_BRANCH." >&2
    exit 1
  fi
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
