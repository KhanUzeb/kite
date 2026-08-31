# Post-merge release checklist (harness upgrade batch)

After merging the harness upgrade PRs to `main`, cut a release:

## PR merge order (recommended)

1. #7 — `feat(bench): baseline benchmarks`
2. #8 — `feat(tools): ToolResult contract`
3. #9 — `feat(context): execution cwd + host mode`
4. #10 — `feat(agent): cancellation + parallel tools`
5. This PR — release bump script only (merge last or use locally)

## Bump version and tag

```bash
chmod +x scripts/bump_release.sh
./scripts/bump_release.sh 0.7.1
```

Edit `CHANGELOG.md` if needed, then:

```bash
git push origin main --tags
```

## Verify before tagging

```bash
pytest -q
kite bench --json
```

## Harness upgrade validation report

Capture a before/after benchmark delta after merge:

```bash
git checkout main~1  # optional baseline commit
kite bench --save /tmp/before.json
git checkout main
kite bench --compare /tmp/before.json
```
