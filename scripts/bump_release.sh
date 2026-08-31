#!/usr/bin/env bash
# Bump Kite version, prepend CHANGELOG stub, and create an annotated git tag.
#
# Usage (after harness upgrade PRs are merged to main):
#   ./scripts/bump_release.sh 0.7.0
#
# Then review CHANGELOG.md, commit, and push with tags:
#   git push origin main --tags

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

python - "$NEW" <<'PY'
import re
import sys
from pathlib import Path

new = sys.argv[1]
root = Path(".")
pyproject = root / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
text, n = re.subn(r'(?m)^version = "[^"]+"', f'version = "{new}"', text, count=1)
if n != 1:
    raise SystemExit("could not update pyproject.toml version")
pyproject.write_text(text, encoding="utf-8")

init = root / "src" / "kite" / "__init__.py"
itext = init.read_text(encoding="utf-8")
itext, n = re.subn(r'__version__ = "[^"]+"', f'__version__ = "{new}"', itext, count=1)
if n != 1:
    raise SystemExit("could not update kite __version__")
init.write_text(itext, encoding="utf-8")
print(f"bumped project files to {new}")
PY

CHANGELOG="$ROOT/CHANGELOG.md"
STUB="## [$NEW] - $DATE

### Added
- Harness benchmark suite (\`kite bench\`) with BEFORE/AFTER compare tables.
- \`ToolResult\` contract and tool scheduling metadata.
- \`WorkspaceContext\` with separate \`execution_cwd\`, \`set_cwd\` tool, and host/restricted modes.
- Parallel read-only tool execution and end-to-end bash cancellation.

### Changed
- Guardrails follow live execution cwd; host mode allows explicit external paths.

"

if grep -q "^## \[$NEW\]" "$CHANGELOG"; then
  echo "CHANGELOG already has section for $NEW" >&2
else
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

git add pyproject.toml src/kite/__init__.py CHANGELOG.md
git commit -m "chore: release v$NEW"

if git rev-parse "v$NEW" >/dev/null 2>&1; then
  echo "tag v$NEW already exists — skipping tag create" >&2
else
  git tag -a "v$NEW" -m "Kite v$NEW"
  echo "created tag v$NEW"
fi

echo ""
echo "Done. Review CHANGELOG.md, then:"
echo "  git push origin main --tags"
