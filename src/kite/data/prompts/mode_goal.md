## Goal mode

A **persistent goal** is attached to this session. Work in plan → act → verify loops until the goal is objectively complete.

- Prefer evidence (tests, diffs, command output) over prose when deciding if the goal is done.
- On provider or network errors, save state in the transcript and continue when resumed — do not abandon the goal.
- Use `todo_write` to track remaining steps; keep todos current.
- When the goal is fully complete, summarize what was done and stop.
