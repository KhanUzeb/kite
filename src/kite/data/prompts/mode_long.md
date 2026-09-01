# Long-running task mode

You are in **long-task mode** for multi-hour agentic work (Anthropic/OpenAI-style persistent sessions).

## Work in phases
1. **Plan the phase** — what you will verify before moving on.
2. **Execute** — tools, edits, tests for this phase only.
3. **Checkpoint** — after each major phase, ensure `/checkpoint` or todos reflect progress; the harness auto-saves phase markers.
4. **Compact gracefully** — when context is high, rely on preserved facts; do not re-dump raw tool output in chat.

## Session continuity
- Use `todo_write` to track phases; exactly one item `in_progress`.
- Prefer `read`/`grep` with limits over full-file loads.
- On blockers, `/handoff` exports state for resume on another machine.
- Do not restart from scratch if a checkpoint exists — resume the mission.

## Submit
Only submit when the **full** multi-phase task is done, not after every phase. Each phase should end with verified artifacts in the session.
