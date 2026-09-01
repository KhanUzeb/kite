"""Slash command parsing and CLI help."""

from __future__ import annotations

from kite.cli.slash import CommandIndex, help_text
from kite.ui.commands import parse_slash
from kite.ui.repl import ChatSession


def test_model_select_provider_builtins() -> None:
    r = parse_slash("/select groq")
    assert r.kind == "handled"
    assert r.command == "select"
    assert r.arg == "groq"
    assert r.legacy == ""

    r = parse_slash("/models anthropic")
    assert r.command == "models"
    assert r.arg == "anthropic"

    r = parse_slash("/provider groq")
    assert r.command == "provider"
    assert r.arg == "groq"


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


def test_legacy_slash_routing() -> None:
    session = ChatSession.__new__(ChatSession)
    cmd, arg = session._apply_legacy_slash("model", "groq", "select")
    assert cmd == "model"
    assert arg == "select groq"

    cmd, arg = session._apply_legacy_slash("memory", "", "semantic")
    assert cmd == "memory"
    assert arg == "semantic"


def test_help_text_groups() -> None:
    text = help_text(CommandIndex.load("."))
    assert "session" in text
    assert "model & keys" in text
    assert "/checkpoint" in text
    assert "legacy aliases" in text
    assert "/select" in text
    assert "/provider" in text


def test_legacy_names_in_command_index() -> None:
    index = CommandIndex.load(".")
    assert index.get("thinking") is not None
    assert index.get("select") is not None


def test_cmd_help(capsys) -> None:
    import argparse

    from kite.cli.help_map import cli_help_text
    from kite.cli.run import cmd_help

    assert "kite run" in cli_help_text()
    assert cmd_help(argparse.Namespace()) == 0
    assert "kite setup" in capsys.readouterr().out


def test_strip_ansi_helper() -> None:
    from tests.conftest import strip_ansi

    colored = "\x1b[32m+2\x1b[0m\x1b[2m,\x1b[0m\x1b[31m-1\x1b[0m"
    assert strip_ansi(colored) == "+2,-1"
