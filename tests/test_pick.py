"""Numbered CLI/REPL pickers."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock

from kite.ui.pick import confirm, numbered_pick


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


def test_numbered_pick_by_id() -> None:
    console = MagicMock()
    console.input.return_value = "gamma"
    chosen = numbered_pick(
        console,
        [("a", "alpha"), ("b", "beta"), ("c", "gamma")],
        current=None,
        title="t",
        noun="model",
    )
    assert chosen == "c"


def test_confirm_default_yes() -> None:
    console = MagicMock()
    console.input.return_value = ""
    assert confirm(console, "Delete?", default=True) is True
    console.input.return_value = "n"
    assert confirm(console, "Delete?", default=True) is False


def test_confirm_default_no() -> None:
    console = MagicMock()
    console.input.return_value = ""
    assert confirm(console, "Delete?", default=False) is False
    console.input.return_value = "yes"
    assert confirm(console, "Delete?", default=False) is True


def test_resume_without_id_non_tty(monkeypatch) -> None:
    monkeypatch.setattr("kite.ui.pick.can_prompt", lambda: False)
    from kite.cli.run import cmd_resume

    assert cmd_resume(argparse.Namespace(session=None)) == 2


def test_models_parser_has_list_flag() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["models", "--list", "-p", "groq"])
    assert args.list is True
    assert args.provider == "groq"
    args = build_parser().parse_args(["resume"])
    assert args.session is None
