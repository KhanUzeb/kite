# Kite examples

Inspired by [MiniMax Code examples](https://github.com/MiniMax-AI/minimax-code/blob/main/docs/examples.md). Run commands from any project directory with Kite installed (`kite` or `python -m kite` from a dev checkout).

## 1. Edit code and run tests

[`examples/clamp`](../examples/clamp) is an intentionally broken `clamp()` with pytest tests. Copy the folder elsewhere before trying it so you do not commit the fix into the harness repo.

```bash
cd /path/to/copy/of/clamp
pytest -q
kite run "Read clamp.py and test_clamp.py. Run pytest, fix clamp without changing tests, run pytest again."
```

Resume the latest session in the same directory:

```bash
kite --continue
# or
kite resume --last
```

## 2. Bootstrap agent guidance (AGENTS.md)

When a git repo has no root `AGENTS.md`:

```bash
kite init .
kite init --chat    # interactive init skill
```

In the REPL: `/init` (add `--force` to overwrite with backup).

## 3. Choose your own model

```bash
kite setup
kite keys --set groq
kite models -p groq --select
kite run --headless "Summarize the test entry points in this repo"
```

Use `kite providers` and `kite config --set-model` for saved defaults. See [kite_commands.md](../kite_commands.md).

## 4. Attach files and images

```bash
kite run --attach ./screenshot.png "Describe this UI and suggest three improvements"
```

In the REPL, reference paths inline (`fix @src/foo.py`) or use `/attach` / F8 clipboard attach.

## 5. Headless / CI

```bash
kite exec "run pytest -q" --json
kite tasks run ~/.kite/tasks/example.jsonl
```

`kite exec` is an alias for one-shot `kite run` with auto-approval and quiet output.
