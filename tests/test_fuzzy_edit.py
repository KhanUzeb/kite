"""Fuzzy edit fallback when unique line-trimmed match exists."""

from __future__ import annotations

from pathlib import Path

from kite.tools.coding import make_coding_tools


def test_edit_fuzzy_line_trimmed_match(workspace: Path) -> None:
    target = workspace / "sample.py"
    target.write_text("def foo():\n    return 1\n", encoding="utf-8")
    tools = {t.name: t for t in make_coding_tools(cwd=str(workspace), enabled=["edit"])}
    edit = tools["edit"]
    result = edit.run(
        {
            "path": "sample.py",
            "old": "def foo():  \n    return 1  ",
            "new": "def foo():\n    return 2\n",
        }
    )
    assert result["ok"], result
    assert "return 2" in target.read_text(encoding="utf-8")
