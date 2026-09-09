# Kite v0.9.6

**Date:** 2026-09-09

## Highlights

- **Security hardening** — recursive redaction, session persistence policy, process-tree teardown, child-env isolation, skill trust, SSRF with connect-time peer checks, and harness OS protection (`/proc` `/sys` `/dev`; restricted mode blocks all network tools).
- **BYOS auth** — ChatGPT/Codex, Claude Code, and Grok logins go through official provider runtimes instead of LiteLLM private OAuth.
- **Subagents** — orchestration + crew TUI, bundled personas, `kite subagents` / `/agents`, live crew stream, `USER.md` / `PROFILE.md` / `WORKING.md`.
- **Themes** — palettes (including transparent composer chrome) wired through the TUI; `/theme` and `/font`.
- **Resume + goals** — `/goal` survives provider errors; recovery continue and `kite resume --retry`.
- **Web tools** — webfetch returns readable text; websearch ranking/dedupe; stricter URL/OS guards.
- **Headless** — `kite tasks` JSONL batches and `kite run --headless` for CI/cron.
- **Faster `/` menu** — slash completion prewarms on REPL startup.

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 0.9.6
```

## Subagents and personas

```bash
kite subagents                     # bundled + ~/.kite/subagents
kite subagents --init auditor --role debugger --label "Auditor"
# REPL: /agents   /agents profiles   /live agents
```

## Headless tasks

```bash
kite tasks init
kite tasks run ~/.kite/tasks/example.jsonl
kite run --headless "fix the failing test"
```

## Privacy and restricted mode

```bash
kite privacy
kite config --session-persistence redacted
# REPL: /privacy sessions   /restricted on
```

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [0.9.6] entry.

This release integrates PRs #49–#59 via [#60](https://github.com/KhanUzeb/kite/pull/60).
