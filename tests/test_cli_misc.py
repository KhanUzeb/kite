"""CLI apply, pickers, slash help, routing, benchmarks."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

from kite.cli.apply_cmd import _path_inside_workspace, apply_unified_diff
from kite.cli.slash import CommandIndex, help_text
from kite.ui.commands import LEGACY_ALIASES, parse_slash
from kite.ui.pick import numbered_pick
from kite.ui.repl import ChatSession

# --- apply ---


def test_sibling_prefix_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "root2"
    sibling.mkdir()
    assert not _path_inside_workspace(sibling, root)


def test_apply_unified_diff_flushes_last_file(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("hello\n", encoding="utf-8")
    diff = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-hello
+world
"""
    result = apply_unified_diff(diff, cwd=str(tmp_path))
    assert result["count"] == 1
    assert target.read_text(encoding="utf-8") == "world\n"


# --- pick ---


def test_numbered_pick_by_index() -> None:
    console = MagicMock()
    console.input.return_value = "2"
    chosen = numbered_pick(
        console,
        [("a", "alpha"), ("b", "beta"), ("c", "gamma")],
        current="a",
        title="t",
        noun="model",
    )
    assert chosen == "b"


def test_numbered_pick_cancel_empty() -> None:
    console = MagicMock()
    console.input.return_value = ""
    assert numbered_pick(console, [("a", "alpha")], current=None, title="t", noun="item") is None


def test_resume_without_id_non_tty(monkeypatch) -> None:
    monkeypatch.setattr("kite.ui.pick.can_prompt", lambda: False)
    from kite.cli.run import cmd_resume

    assert cmd_resume(argparse.Namespace(session=None)) == 2


def test_headless_auto_approver_allows_inside_and_denies_outside(tmp_path: Path) -> None:
    from kite.agent.harness import Harness, HarnessConfig
    from kite.cli.run import _wire_display

    harness = Harness(HarnessConfig(cwd=str(tmp_path), approval="auto"))
    args = argparse.Namespace(
        mode="build",
        approval="auto",
        headless=True,
        quiet=False,
        no_stream=False,
        verbose=False,
        cwd=str(tmp_path),
        config=None,
    )

    _wire_display(harness, MagicMock(), args)

    assert harness.approver("write", {"path": str(tmp_path / "inside.txt")}, {}) == "allow"
    assert harness.approver("write", {"path": str(tmp_path.parent / "outside.txt")}, {}) == "deny"


# --- slash / help ---


def test_model_select_provider_builtins() -> None:
    assert parse_slash("/select groq").command == "select"
    assert parse_slash("/models anthropic").command == "models"
    assert parse_slash("/thinking").command == "reasoning"


def test_legacy_slash_routing() -> None:
    session = ChatSession.__new__(ChatSession)
    cmd, arg = session._apply_legacy_slash("model", "groq", "select")
    assert cmd == "model"
    assert arg == "select groq"


def test_help_text_groups() -> None:
    text = help_text(CommandIndex.load("."))
    assert "session" in text
    assert "/select" in text


def test_skill_not_legacy_alias() -> None:
    assert "skill" not in LEGACY_ALIASES
    assert "collapse" not in LEGACY_ALIASES


def test_parse_skill_routes_to_skill_not_skills() -> None:
    hit = parse_slash("/skill commit")
    assert hit.kind == "handled"
    assert hit.command == "skill"
    assert hit.arg == "commit"


def test_parse_collapse_stays_collapse() -> None:
    hit = parse_slash("/collapse")
    assert hit.command == "collapse"


# --- bench (see tests/test_bench.py for budget gates) ---
