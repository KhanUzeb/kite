#!/usr/bin/env bash
# kite-release-version: 0.9.3
# Bump Kite version, sync stamped files, prepend CHANGELOG stub, tag, and push.
#
# Usage (after changes are merged to main):
#   ./scripts/bump_release.sh 0.9.3
#
# Then edit CHANGELOG.md and docs/RELEASE-X.Y.Z.md, commit if needed, push:
#   git push origin main --tags
#
# Pushing tag vX.Y.Z triggers .github/workflows/release.yml (GitHub release).

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <new-version>" >&2
  exit 1
fi

NEW="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CURRENT="$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
DATE="$(date -u +%Y-%m-%d)"

if [[ "$NEW" == "$CURRENT" ]]; then
  echo "version already $CURRENT" >&2
  exit 1
fi

echo "syncing version stamps to $NEW ..."
python scripts/sync_version.py "$NEW"

RELEASE_DOC="docs/RELEASE-$NEW.md"
if [[ ! -f "$RELEASE_DOC" ]]; then
  cat > "$RELEASE_DOC" <<EOF
# Kite v$NEW

**Date:** $DATE

## Highlights

(TODO: one paragraph summary)

---

## Upgrade

\`\`\`bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # $NEW
\`\`\`

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [$NEW] entry.
EOF
  echo "created stub $RELEASE_DOC"
fi

CHANGELOG="$ROOT/CHANGELOG.md"
if ! grep -q "^## \[$NEW\]" "$CHANGELOG"; then
  STUB="## [$NEW] - $DATE

### Added
-

### Changed
-

### Fixed
-

"
  python - "$CHANGELOG" "$STUB" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
stub = sys.argv[2]
text = path.read_text(encoding="utf-8")
marker = "\n## ["
idx = text.find(marker)
if idx == -1:
    body = text.rstrip() + "\n\n" + stub
else:
    body = text[:idx].rstrip() + "\n\n" + stub + text[idx + 1 :]
path.write_text(body, encoding="utf-8")
print(f"prepended CHANGELOG section for {stub.splitlines()[0]}")
PY
fi

python scripts/sync_version.py --check

git add pyproject.toml src/kite/__init__.py CHANGELOG.md README.md AGENTS.md architecture.md docs/cli-ux.md docs/kite-system-design.md docs/ideal-cli-spec.md scripts/ "$RELEASE_DOC"
git commit -m "chore: release v$NEW"

if git rev-parse "v$NEW" >/dev/null 2>&1; then
  echo "tag v$NEW already exists — skipping tag create" >&2
else
  git tag -a "v$NEW" -m "Kite v$NEW"
  echo "created tag v$NEW"
fi

echo ""
echo "Done. Edit CHANGELOG.md and $RELEASE_DOC, amend if needed, then:"
echo "  git push origin main --tags"
echo ""
echo "Tag push publishes the GitHub release via .github/workflows/release.yml"
