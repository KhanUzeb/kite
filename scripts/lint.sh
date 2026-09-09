#!/usr/bin/env bash
# kite-release-version: 0.9.5
# Local pre-PR checks — mirrors .github/workflows/tests.yml (minus matrix).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage: ./scripts/lint.sh [options]

Runs the same gates as CI on a single Python (current interpreter):
  sync_version --check
  ruff check src tests
  pytest -q                    # includes test_security_* + test_guardrails
  kite bench --check

Options:
  --no-pytest   Skip pytest
  --no-bench    Skip kite bench --check
  --ruff-all    Also lint scripts/ (not required for CI)
  -h, --help    Show this help
EOF
}

RUN_PYTEST=1
RUN_BENCH=1
RUFF_ALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-pytest) RUN_PYTEST=0; shift ;;
    --no-bench) RUN_BENCH=0; shift ;;
    --ruff-all) RUFF_ALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

export KITE_HOME="${KITE_HOME:-${TMPDIR:-/tmp}/kite-lint-$$}"
export KITE_SKIP_SETUP=1
mkdir -p "${KITE_HOME}"

echo "== sync_version =="
python scripts/sync_version.py --check

echo "== ruff (src tests) =="
if command -v uv >/dev/null 2>&1; then
  uv run ruff check src tests
else
  ruff check src tests
fi

if [[ "${RUFF_ALL}" -eq 1 ]]; then
  echo "== ruff (scripts) =="
  if command -v uv >/dev/null 2>&1; then
    uv run ruff check scripts
  else
    ruff check scripts
  fi
fi

if [[ "${RUN_PYTEST}" -eq 1 ]]; then
  echo "== pytest =="
  if command -v uv >/dev/null 2>&1; then
    uv run pytest -q
  else
    pytest -q
  fi
fi

if [[ "${RUN_BENCH}" -eq 1 ]]; then
  echo "== kite bench --check =="
  if command -v uv >/dev/null 2>&1; then
    uv run python -m kite.cli.run bench --check
  else
    python -m kite.cli.run bench --check
  fi
fi

echo ""
echo "lint.sh: all requested checks passed."
