#!/usr/bin/env bash
# kite-release-version: 1.0.6
# Create an independent checkout, venv and Kite home without changing the global CLI.
set -euo pipefail
if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Usage: scripts/worktree.sh <name> (letters, numbers, dots, underscores, hyphens)" >&2
  exit 2
fi
ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
DEST="$(dirname "$ROOT")/$(basename "$ROOT")-$1"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
if [[ -e "$DEST" ]]; then
  echo "Refusing to overwrite $DEST" >&2
  exit 1
fi
git -C "$ROOT" worktree add -b "agent/$1" "$DEST"
# Use this script's installer: the new worktree starts at committed HEAD.
KITE_HOME="$DEST/.venv/kite-home" bash "$ROOT/scripts/install.sh" --dev --local --no-clone --dir "$DEST"
chmod 700 "$DEST/.venv/kite-home"
printf '\nIsolated worktree ready (committed HEAD; uncommitted edits are not copied):\n'
printf '  cd %q\n' "$DEST"
printf '  source .venv/bin/activate\n'
printf '  export KITE_HOME=%q KITE_SKIP_SETUP=1 KITE_TYPED_PICK=1\n' "$DEST/.venv/kite-home"
printf '  ./scripts/ci_check.sh --fast\n  ./scripts/ci_check.sh\n'
printf '  python scripts/e2e_smoke.py\n'
