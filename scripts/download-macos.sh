#!/usr/bin/env bash
# kite-release-version: 0.9.6
# Download and install Kite on macOS — curl one-liner entry point.
#
#   curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download-macos.sh | bash
#   curl -fsSL .../download-macos.sh | bash -s -- --setup
#
# Forwards all arguments to scripts/install.sh (e.g. --dir, --setup, --verify).
set -euo pipefail

REPO_SLUG="${KITE_REPO_SLUG:-KhanUzeb/kite}"
BRANCH="${KITE_BRANCH:-main}"
RAW_BASE="${KITE_RAW_BASE:-https://raw.githubusercontent.com/${REPO_SLUG}/${BRANCH}}"

usage() {
  cat <<EOF
Usage: download-macos.sh [install.sh options]

macOS-only bootstrap. Downloads scripts/install.sh from GitHub and runs it.

One-liner:
  curl -fsSL ${RAW_BASE}/scripts/download-macos.sh | bash
  curl -fsSL ${RAW_BASE}/scripts/download-macos.sh | bash -s -- --setup

Options are passed through to install.sh (--dir, --setup, --verify, …).
Environment:
  KITE_INSTALL_DIR   default install path (~/kite)
  KITE_BRANCH        git branch for raw scripts (default: main)
  KITE_REPO_SLUG     GitHub owner/repo (default: KhanUzeb/kite)
EOF
}

if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "download-macos.sh is for macOS only." >&2
  echo "On Linux, use:" >&2
  echo "  curl -fsSL ${RAW_BASE}/scripts/install.sh | bash" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not found." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git not found — install Xcode Command Line Tools:" >&2
  echo "  xcode-select --install" >&2
  exit 1
fi

TMP_INSTALL="$(mktemp -t kite-install)"
cleanup() { rm -f "${TMP_INSTALL}"; }
trap cleanup EXIT

echo "Downloading install.sh (${BRANCH})..."
curl -fsSL "${RAW_BASE}/scripts/install.sh" -o "${TMP_INSTALL}"
chmod +x "${TMP_INSTALL}"
exec bash "${TMP_INSTALL}" "$@"
