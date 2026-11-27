"""Mistake recovery in the CLI and REPL: help topics, config values, slash typos.

The failure these cover is always the same: a small mistake produced either a
generic answer ("type /help"), a silent change, or an expensive misdirected
agent run. The fix keeps the established output surfaces and only adds the
specific next action.
"""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from kite.cli import run as cli_run
from kite.cli.slash import CommandIndex, expand_prompt_slash, resolve_slash
from kite.config import UserConfig
from kite.util.suggest import closest, did_you_mean
from tests.conftest import strip_ansi


def _console(buf: StringIO) -> Console:
    return Console(file=buf, force_terminal=False, width=160)


def test_suggestion_helper_folds_separator_styles_and_keeps_quiet_when_unrelated() -> None:
    assert closest("sessons", ["sessions", "models"]) == ["sessions"]
    assert did_you_mean("staus", ["/status", "/stop"]) == "did you mean '/status'?"
    # Hyphen/underscore spelling mistakes are real typos, not an exact match.
    assert len(closest("webkeys", ["web-keys", "web_keys"])) == 1
    assert did_you_mean("status", ["status"]) == ""
    assert did_you_mean("zzzzzz", ["status", "models"]) == ""


def test_help_topic_prints_that_subcommands_help(capsys: pytest.CaptureFixture[str], kite_home: Path) -> None:
    assert cli_run.cmd_help(argparse.Namespace(topic="run")) == 0
    out = capsys.readouterr().out
    assert "usage: kite run" in out
    assert "--headless" in out and "Task prompt" in out
    assert "Kite CLI\n" not in out, "a topic must not fall back to the generic map"


def test_help_unknown_topic_suggests_then_keeps_the_brief_map(
    capsys: pytest.CaptureFixture[str], kite_home: Path
) -> None:
    assert cli_run.cmd_help(argparse.Namespace(topic="modles")) == 0
    out = capsys.readouterr().out
    assert out.index("did you mean 'models'?") < out.index("Kite CLI")
    assert 'kite run "task"' in out


def test_help_all_still_prints_the_full_map(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_run.cmd_help(argparse.Namespace(topic="all")) == 0
    out = capsys.readouterr().out
    assert "Kite CLI - full reference" in out and "kite_commands.md" in out


def test_config_rejects_unknown_provider_before_saving(kite_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = UserConfig.load()
    cfg.default_provider = "groq"
    cfg.save()
    buf = StringIO()
    monkeypatch.setattr(cli_run, "_console", lambda: _console(buf))
    parser = cli_run.build_parser()

    assert cli_run.cmd_config(parser.parse_args(["config", "--set-provider", "groqo"])) == 2
    output = strip_ansi(buf.getvalue())
    assert "unknown provider groqo" in output
    assert "did you mean 'groq'?" in output
    assert UserConfig.load().default_provider == "groq", "a bad value must not be persisted"

    assert cli_run.cmd_config(parser.parse_args(["config", "--set-provider", "groq"])) == 0
    assert UserConfig.load().default_provider == "groq"


def test_config_auto_compact_rejects_typos_instead_of_silently_disabling(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = cli_run.build_parser()
    assert parser.parse_args(["config", "--auto-compact", "YES"]).auto_compact is True
    assert parser.parse_args(["config", "--auto-compact", "0"]).auto_compact is False
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert "--auto-compact true|false" in subparsers.choices["config"].format_help()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["config", "--auto-compact", "maybe"])
    assert exc.value.code == 2
    assert "expected true|false" in capsys.readouterr().err


def test_unknown_slash_suggests_a_close_command(workspace: Path) -> None:
    index = CommandIndex.load(workspace)
    result = resolve_slash("/staus", index)
    assert result.kind == "unknown"
    assert "did you mean '/status'?" in result.message
    assert "/help" in result.message
    unrelated = resolve_slash("/zzzzzz", index)
    assert "did you mean" not in unrelated.message
    assert "type /help" in unrelated.message


def test_one_shot_slash_expansion_reports_the_same_suggestion(workspace: Path) -> None:
    with pytest.raises(RuntimeError, match="did you mean '/status'\\?"):
        expand_prompt_slash("/staus", cwd=workspace)


def test_unknown_skill_suggests_a_loaded_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.skills.loader import Skill

    skill = Skill(name="commit", path=Path("commit.md"), content="body")
    index = CommandIndex(specs={}, skills=[skill], plugins=[], commands=[])
    monkeypatch.setattr("kite.skills.loader.expand_skill_slash", lambda *_a, **_k: None)
    result = resolve_slash("/skill comit", index)
    assert result.kind == "unknown"
    assert "did you mean 'commit'?" in result.message
    assert "/skills" in result.message
