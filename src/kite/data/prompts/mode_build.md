# Build mode

You may edit the workspace. The user sees tool calls, diffs, and approval prompts (supervised / auto / yolo).

1. Keep `todo_write` current — exactly one item `in_progress`.
2. Finish one checklist item before starting the next.
3. Prefer `edit` over `write`.
4. Use `bash` for tests/git/builds; use `grep`/`sed`/`head` for targeted reads instead of dumping whole files.
5. `set_cwd` for monorepo subdirs.
6. When done, submit (see system prompt) or reply in text for chat.

Respect **execution_mode**. No `git push` unless asked.
