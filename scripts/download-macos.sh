#!/usr/bin/env bash
# kite-release-version: 0.9.6
# macOS entry point — forwards to download.sh (macOS + Linux bootstrap).
#
#   curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download-macos.sh | bash
#   curl -fsSL …/download-macos.sh | bash -s -- --setup
set -euo pipefail

REPO_SLUG="${KITE_REPO_SLUG:-KhanUzeb/kite}"
BRANCH="${KITE_BRANCH:-main}"
RAW_BASE="${KITE_RAW_BASE:-https://raw.githubusercontent.com/${REPO_SLUG}/${BRANCH}}"

if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  cat <<EOF
Usage: download-macos.sh [install.sh options]

macOS-friendly alias for download.sh. Same one-liner works on Ubuntu/Linux via download.sh.

  curl -fsSL ${RAW_BASE}/scripts/download-macos.sh | bash
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash          # macOS or Linux
  irm ${RAW_BASE}/scripts/install.ps1 | iex                  # Windows
EOF
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "download-macos.sh is for macOS. On Linux use:" >&2
  echo "  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash" >&2
  echo "Or:" >&2
  echo "  curl -fsSL ${RAW_BASE}/scripts/install.sh | bash" >&2
  exit 1
fi

TMP="$(mktemp "${TMPDIR:-/tmp}/kite-download.XXXXXX")"
cleanup() { rm -f "${TMP}"; }
trap cleanup EXIT

curl -fsSL "${RAW_BASE}/scripts/download.sh" -o "${TMP}"
if command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "${TMP}" 2>/dev/null || true
fi
chmod +x "${TMP}"
exec bash "${TMP}" "$@"
