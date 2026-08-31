"""Slash command parsing and CLI help."""

from __future__ import annotations

from kite.ui.commands import parse_slash


def test_legacy_model_aliases() -> None:
    r = parse_slash("/select groq")
    assert r.kind == "handled"
    assert r.command == "model"
    assert r.legacy == "select"

    r = parse_slash("/models anthropic")
    assert r.command == "model"
    assert r.legacy == "models"

    r = parse_slash("/provider groq")
    assert r.command == "model"
    assert r.legacy == "provider"


def test_legacy_status_and_memory() -> None:
    assert parse_slash("/cost").command == "status"
    assert parse_slash("/semantic").command == "memory"
    assert parse_slash("/episodic").command == "memory"
    assert parse_slash("/thinking").command == "reasoning"


def test_model_subcommand_still_builtin() -> None:
    r = parse_slash("/model list groq")
    assert r.kind == "handled"
    assert r.command == "model"
    assert r.arg == "list groq"


def test_cmd_help(capsys) -> None:
    import argparse

    from kite.cli.help_map import cli_help_text
    from kite.cli.run import cmd_help

    assert "kite run" in cli_help_text()
    assert cmd_help(argparse.Namespace()) == 0
    assert "kite setup" in capsys.readouterr().out
