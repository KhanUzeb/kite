# Fix the clamp function

This intentionally incorrect function is a small coding exercise (same idea as [MiniMax Code `examples/clamp`](https://github.com/MiniMax-AI/minimax-code/tree/main/examples/clamp)). Copy this directory elsewhere before trying it so you do not commit the fix into the Kite harness repo by accident.

Ask Kite to read the function and tests, reproduce the failure, fix the function without changing the tests, and run the tests again.

```bash
cd examples/clamp
pytest -q
kite run "Read clamp.py and test_clamp.py. Run pytest, fix clamp without changing tests, run pytest again."
```

Expected: `clamp(5, 0, 10)` → `5`, `clamp(-3, 0, 10)` → `0`, `clamp(14, 0, 10)` → `10`.
