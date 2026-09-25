#!/usr/bin/env bash
# kite-release-version: 1.0.2
# Same gates as .github/workflows/tests.yml — run before push to main.
set -euo pipefail
RELEASE=0
if [[ "${1:-}" == "--release" ]]; then
  RELEASE=1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export KITE_SKIP_SETUP="${KITE_SKIP_SETUP:-1}"
export KITE_TYPED_PICK="${KITE_TYPED_PICK:-1}"
if [[ -z "${KITE_HOME:-}" ]]; then
  export KITE_HOME="${TMPDIR:-/tmp}/kite-ci-home"
  mkdir -p "$KITE_HOME"
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
echo "== ruff"
"$PYTHON" -m ruff check src tests
echo "== pytest"
"$PYTHON" -m pytest -q --tb=short -p faulthandler
echo "== kite bench --check"
"$PYTHON" -m kite.cli.run bench --check
echo "CI gates ok"
