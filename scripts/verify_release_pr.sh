#!/usr/bin/env bash
# Pre-merge / post-merge checks for v0.7.1 release PR (#18).
# Usage:
#   ./scripts/verify_release_pr.sh              # on release branch or main
#   ./scripts/verify_release_pr.sh --pr 18      # also check GitHub PR state
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

EXPECTED="0.7.1"

# Version in package metadata
VER="$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
[[ "$VER" == "$EXPECTED" ]] || fail "pyproject.toml version is $VER, expected $EXPECTED"
ok "pyproject.toml version $VER"

PKG_VER="$(python -c "import kite; print(kite.__version__)")"
[[ "$PKG_VER" == "$EXPECTED" ]] || fail "kite.__version__ is $PKG_VER, expected $EXPECTED"
ok "kite.__version__ $PKG_VER"

# Release docs
[[ -f docs/RELEASE-0.7.1.md ]] || fail "missing docs/RELEASE-0.7.1.md"
grep -q "0.7.1" CHANGELOG.md || fail "CHANGELOG.md missing 0.7.1 section"
ok "release docs present"

# CI workflow — no batch gate
if grep -q "run_tests=false" .github/workflows/tests.yml 2>/dev/null; then
  fail "CI workflow still has batch skip logic"
fi
grep -q "pull_request" .github/workflows/tests.yml || fail "CI missing pull_request trigger"
ok "CI workflow runs on push/PR (no batch gate)"

# Tests
export KITE_HOME="${KITE_HOME:-${TMPDIR:-/tmp}/kite-verify-$$}"
export KITE_SKIP_SETUP=1
mkdir -p "$KITE_HOME"
if command -v pytest >/dev/null 2>&1; then
  pytest -q
  ok "pytest passed"
else
  echo "SKIP: pytest not installed (run: uv pip install -e '.[dev]')"
fi

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
