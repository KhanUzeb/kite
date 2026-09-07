#!/usr/bin/env bash
# kite-release-version: 0.9.5
# Pre-release checks on main or a release branch.
# Usage:
#   ./scripts/verify_release_pr.sh
#   ./scripts/verify_release_pr.sh --pr 18
set -euo pipefail

PR=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr) PR="$2"; shift 2 ;;
    -h|--help)
      echo "usage: $0 [--pr N]"
      exit 0
      ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK: $*"; }

EXPECTED="$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"

python scripts/sync_version.py --check || fail "version stamps out of sync (run: python scripts/sync_version.py)"
ok "version stamps synced ($EXPECTED)"

grep -q "pull_request" .github/workflows/tests.yml || fail "CI missing pull_request trigger"
ok "CI workflow runs on push/PR"

grep -q "bench --check" .github/workflows/tests.yml || fail "CI missing kite bench --check gate"
ok "CI workflow runs bench budget check"

# Tests
export KITE_HOME="${KITE_HOME:-${TMPDIR:-/tmp}/kite-verify-$$}"
export KITE_SKIP_SETUP=1
mkdir -p "$KITE_HOME"
command -v pytest >/dev/null 2>&1 || fail "pytest not installed (run: uv pip install -e '.[dev]')"
pytest -q
python -m kite.cli.run bench --check
ok "pytest passed"

# Optional GitHub PR check
if [[ "$PR" -gt 0 ]]; then
  command -v gh >/dev/null 2>&1 || fail "gh CLI required for --pr"
  STATE="$(gh pr view "$PR" --json mergeable,state -q '.state')"
  MERGEABLE="$(gh pr view "$PR" --json mergeable -q '.mergeable')"
  [[ "$STATE" == "OPEN" ]] || fail "PR #$PR state is $STATE (expected OPEN)"
  [[ "$MERGEABLE" == "MERGEABLE" ]] || fail "PR #$PR mergeable=$MERGEABLE"
  ok "PR #$PR is OPEN and MERGEABLE"
fi

echo ""
echo "All release verification checks passed for v$EXPECTED."
