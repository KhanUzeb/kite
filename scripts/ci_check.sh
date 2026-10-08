#!/usr/bin/env bash
# kite-release-version: 1.0.6
# Core CI gates; run scripts/e2e_smoke.py separately for offline CLI/PTY QA.
set -euo pipefail
RELEASE=0
FAST=0
if [[ "${1:-}" == "--release" ]]; then
  RELEASE=1
  shift
fi
if [[ "${1:-}" == "--fast" ]]; then
  FAST=1
  shift
elif [[ $# -gt 0 ]]; then
  echo "Usage: scripts/ci_check.sh [--release] [--fast [--base REF | --files PATH...]]" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export KITE_SKIP_SETUP="${KITE_SKIP_SETUP:-1}"
export KITE_TYPED_PICK="${KITE_TYPED_PICK:-1}"
if [[ -z "${KITE_HOME:-}" ]]; then
  KITE_HOME="$(mktemp -d "${TMPDIR:-/tmp}/kite-ci-home.XXXXXX")"
  export KITE_HOME
  trap 'rm -rf "$KITE_HOME"' EXIT
fi
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  elif [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then
    PYTHON="$ROOT/.venv/Scripts/python.exe"
  else
    PYTHON="python3"
  fi
fi
echo "Using Python: $PYTHON"
echo "== sync_version --check"
if [[ "$RELEASE" == "1" ]]; then
  "$PYTHON" scripts/sync_version.py --check --release
else
  "$PYTHON" scripts/sync_version.py --check
fi
if [[ "$FAST" == "1" ]]; then
  "$PYTHON" scripts/ci_fast.py "$@"
else
  echo "== ruff"
  "$PYTHON" -m ruff check src tests scripts
  echo "== pytest"
  "$PYTHON" -m pytest -q --tb=short -p faulthandler
fi
echo "== kite bench --check"
"$PYTHON" -m kite.cli.run bench --check
if [[ "$FAST" == "1" ]]; then
  echo "Fast gates ok (run full ci_check.sh before merging)"
else
  echo "CI gates ok"
fi
