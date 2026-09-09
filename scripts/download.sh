#!/usr/bin/env bash
# kite-release-version: 0.9.6
# Cross-platform Unix bootstrap (macOS + Ubuntu/Linux + WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash
#   curl -fsSL …/download.sh | bash -s -- --setup
#
# Downloads install.sh and runs it. Does not clone into your current directory.
# Windows: use install.ps1 instead (see README).
set -euo pipefail

REPO_SLUG="${KITE_REPO_SLUG:-KhanUzeb/kite}"
BRANCH="${KITE_BRANCH:-main}"
RAW_BASE="${KITE_RAW_BASE:-https://raw.githubusercontent.com/${REPO_SLUG}/${BRANCH}}"

usage() {
  cat <<EOF
Usage: download.sh [install.sh options]

Unix bootstrap for macOS and Linux. Downloads scripts/install.sh and runs it.
Installs the kite CLI globally (uv tool) so you can run it from any directory.

One-liner:
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash
  curl -fsSL ${RAW_BASE}/scripts/download.sh | bash -s -- --setup

Windows (PowerShell):
  irm ${RAW_BASE}/scripts/install.ps1 | iex

Options are passed through to install.sh (--setup, --force, --global, …).
Environment:
  KITE_BRANCH        git branch for raw scripts (default: main)
  KITE_REPO_SLUG     GitHub owner/repo (default: KhanUzeb/kite)
  KITE_REPO_REF      git ref for uv tool install (default: main)
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
    echo "If ExecutionPolicy blocks you:" >&2
    echo "  powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm ${RAW_BASE}/scripts/install.ps1 | iex\"" >&2
    exit 1
    ;;
  *)
    echo "Unsupported OS (${uname_s}). Use install.sh manually or see README." >&2
    exit 1
    ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not found." >&2
  case "${uname_s}" in
    Darwin*) echo "  xcode-select --install" >&2 ;;
    Linux*)
      if command -v apt-get >/dev/null 2>&1; then
        echo "  sudo apt-get update && sudo apt-get install -y curl git ca-certificates" >&2
      else
        echo "  Install curl via your package manager." >&2
      fi
      ;;
  esac
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required (uv installs kite from GitHub)." >&2
  case "${uname_s}" in
    Darwin*) echo "  xcode-select --install" >&2 ;;
    Linux*)
      if command -v apt-get >/dev/null 2>&1; then
        echo "  sudo apt-get update && sudo apt-get install -y git" >&2
      else
        echo "  Install git via your package manager." >&2
      fi
      ;;
  esac
  exit 1
fi

# mktemp works on both macOS and Linux; -t prefix is portable enough with template.
TMP_INSTALL="$(mktemp "${TMPDIR:-/tmp}/kite-install.XXXXXX")"
cleanup() { rm -f "${TMP_INSTALL}"; }
trap cleanup EXIT

echo "Downloading install.sh (${BRANCH}) for ${uname_s}..."
curl -fsSL "${RAW_BASE}/scripts/install.sh" -o "${TMP_INSTALL}"
# Drop macOS quarantine if present (Gatekeeper on saved files); no-op elsewhere.
if command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "${TMP_INSTALL}" 2>/dev/null || true
fi
# Strip CRLF if a Windows checkout ever polluted the raw file (portable: no sed -i).
if command -v tr >/dev/null 2>&1 && grep -q $'\r' "${TMP_INSTALL}" 2>/dev/null; then
  tr -d '\r' < "${TMP_INSTALL}" > "${TMP_INSTALL}.lf"
  mv "${TMP_INSTALL}.lf" "${TMP_INSTALL}"
fi
chmod +x "${TMP_INSTALL}"
exec bash "${TMP_INSTALL}" "$@"
