#!/usr/bin/env bash
# kite-release-version: 0.9.6
# macOS entry — forwards to download.sh (raw, then git fallback).
set -euo pipefail

REPO_SLUG="${KITE_REPO_SLUG:-KhanUzeb/kite}"
BRANCH="${KITE_BRANCH:-main}"
REPO_URL="${KITE_REPO_URL:-https://github.com/${REPO_SLUG}.git}"
RAW_BASE="${KITE_RAW_BASE:-https://raw.githubusercontent.com/${REPO_SLUG}/${BRANCH}}"

if [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  cat <<EOF
Usage: download-macos.sh [install.sh options]

  curl -fsSL ${RAW_BASE}/scripts/download-macos.sh | bash

If raw 404s (private repo), use:
  git clone --depth 1 ${REPO_URL} /tmp/kite-get && bash /tmp/kite-get/scripts/install.sh && rm -rf /tmp/kite-get
EOF
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "download-macos.sh is for macOS. On Linux:" >&2
  echo "  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash" >&2
  exit 1
fi

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/kite-macos.XXXXXX")"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

DL="${WORKDIR}/download.sh"
if ! curl -fsSL "${RAW_BASE}/scripts/download.sh" -o "${DL}"; then
  echo "Raw download failed — cloning via git..." >&2
  git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${WORKDIR}/repo"
  exec bash "${WORKDIR}/repo/scripts/download.sh" "$@"
fi
if command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "${DL}" 2>/dev/null || true
fi
chmod +x "${DL}"
exec bash "${DL}" "$@"
