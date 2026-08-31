# Release checklist

After feature work is merged to `main`:

## 1. Bump and sync

```bash
./scripts/bump_release.sh 0.7.3
```

This runs `scripts/sync_version.py`, which updates:

- `pyproject.toml`, `src/kite/__init__.py`
- `README.md`, `AGENTS.md`, `architecture.md`
- `docs/cli-ux.md`, `docs/kite-system-design.md`, `docs/ideal-cli-spec.md`
- **`scripts/*`** — `# kite-release-version:` marker in every `.sh`, `.ps1`, and `.py` under `scripts/`

It also prepends a CHANGELOG stub and creates `docs/RELEASE-X.Y.Z.md` if missing.

## 2. Edit release notes

Fill in `CHANGELOG.md` and `docs/RELEASE-X.Y.Z.md`.

## 3. Verify locally

```bash
python scripts/sync_version.py --check
./scripts/verify_release_pr.sh
```

## 4. Push tag

```bash
git push origin main --tags
```

Pushing `vX.Y.Z` triggers [`.github/workflows/release.yml`](../.github/workflows/release.yml):

- Verifies all version stamps match `pyproject.toml`
- Publishes the GitHub release using `docs/RELEASE-X.Y.Z.md`

Manual publish (fallback):

```bash
gh release create v0.7.3 --title "Kite v0.7.3" --notes-file docs/RELEASE-0.7.3.md
```

## CI guard

Every push/PR runs `python scripts/sync_version.py --check` in the test workflow so stamped docs cannot drift from the package version.
