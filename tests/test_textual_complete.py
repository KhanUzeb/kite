"""Textual slash and @file completion."""

from __future__ import annotations

from kite.cli.slash import CommandIndex
from kite.ui.textual.complete_data import plain_completions


def test_slash_completions_include_help() -> None:
    rows = plain_completions("/h", index_factory=lambda: CommandIndex.load("."))
    names = {row.insert for row in rows}
    assert "help" in names


def test_at_file_completions_for_dot() -> None:
    rows = plain_completions("@.", index_factory=lambda: CommandIndex.load("."))
    assert isinstance(rows, list)
