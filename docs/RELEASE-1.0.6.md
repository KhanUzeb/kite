# Kite v1.0.6

**Date:** 2026-10-05

## Highlights

Quiet release: the terminal stopped shouting. Tool output collapses to a
glanceable line, every truncated body is retrievable again with `/last`, and
the session store stops leaking files.

## The scrollback

A single `edit` used to paint 16 preview lines at start and 40 diff rows at
end. A `todo_write` painted the checklist, a start card, a done card *and* the
raw item JSON — every task item two or three times.

- The task list is now **one line**: `● Tasks 1/3 █████░░░░░░ · edit render.py`,
  with the itemized checklist behind `/tasks`.
- `todo_write` / `todo_read` no longer echo their payload under the checklist
  that already shows it. Status, timing and exit code still print.
- Scroll-printed bodies get a **5-line budget** (`PREVIEW_LINES`): tool output,
  write/edit previews, bash blocks and diffs. Truncation always names the
  command that reveals the rest.
- Approval previews deliberately keep a 40-line window — that is a pause where
  you judge a patch, not scrollback.

## `/last`

The 5-line cap initially shipped a lie: its markers named a `/diff` command
that does not exist, and `/expand` only widens *later* tool calls — so a body
truncated three turns ago had no way back.

`/last` re-prints the previous tool call in full: the record is captured at
tool-end (bounded at 200k chars per payload) and rendered through the existing
formatters, uncollapsed and uncapped. A diff comes back whole.

A regression test cross-checks every overflow marker against the registered
command list, so a hint naming a command that does not exist fails the suite.

## Session storage

- **Deleted sessions leaked a file.** `delete_session` reaped the transcript,
  meta and trajectory but never the `.stats.json` sidecar — one orphan per
  deletion, forever. `delete_all_sessions` now also sweeps sidecars orphaned by
  a crash between unlinks.
- `list_sessions` parsed metadata for every session before applying `limit`.
  It now pre-ranks candidates by transcript/sidecar mtime and parses a bounded
  head. The sidecar matters: `note_runtime` bumps `updated_at` without touching
  the transcript, so ranking on transcript mtime alone reorders wrongly.
- `_trajectory_path` was duplicated byte-for-byte across two modules; one copy
  is gone.
- **Crash tolerance.** Both readers raised `AttributeError` on valid-JSON-but-
  not-an-object rows, and `UnicodeDecodeError` escaped uncaught — it is not an
  `OSError`. `list_session_events` wrapped its whole loop in one
  `JSONDecodeError` handler, so a single torn line discarded *every* event. A
  truncated transcript is the normal post-crash state; all three now degrade to
  the rows that did decode.
- One saved checkpoint counted twice (the loop writes a `context_checkpoint`
  row *and* a `checkpoint` event for the same id). Deduplicated by id.

## Footer

- A turn ending within 125 ms of its last paint could leave the footer frozen
  on the final `working` line until you typed. `clear_running()` is a turn
  boundary and now forces its repaint.
- A flash notification set at an idle prompt outlived its 8 s TTL, because
  expiry was only checked inside `touch()`. `active_flash` expires on read, and
  the composer toolbar uses it.
- `context_pct` divided by a negative context window, rendering `ctx -800%`.

## Tests

141 collected (141 passed, 1 platform skip) — up from 119, still under the 150
CI budget. New: scrollback density, tool-output retrieval, session hygiene,
analytics hygiene, footer throttle.

---

## Upgrade

```bash
git pull
./scripts/install.sh --no-clone
pytest -q
kite --version   # 1.0.6
```

---

## Full changelog

See [CHANGELOG.md](../CHANGELOG.md) for the [1.0.6] entry.
