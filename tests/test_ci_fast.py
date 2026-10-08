from __future__ import annotations

import runpy
from pathlib import Path


def test_changed_file_selection_is_conservative() -> None:
    select = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "ci_fast.py"))["select_tests"]
    assert select(["src/kite/bench/full.py"]) == ["tests/test_bench.py"]
    assert select(["tests/test_bench.py"]) == ["tests/test_bench.py"]
    assert select(["CONTRIBUTING.md"]) == []
    assert select(["src/kite/agent/loop.py"]) == ["tests"]
    assert select(["tests/conftest.py"]) == ["tests"]
    assert select(["src/kite/data/prompts/system.md"]) == ["tests"]
