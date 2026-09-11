"""Minimal CLI / REPL surface — progressive disclosure."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.mode import AgentMode, ApprovalMode
from kite.cli.help_map import CLI_EPILOG, cli_help_brief, cli_help_text
from kite.cli.run import build_parser
from kite.cli.slash import CommandIndex, help_text
from kite.ui.commands import is_primary_slash, parse_slash, primary_builtins
from kite.ui.complete import SlashCompleter, _visible_specs
from kite.ui.state import SessionUiState
from kite.ui.status import render_status, status_segments
from kite.ui.style import KITE_THEME
from tests.conftest import strip_ansi


def test_cli_brief_and_full_help() -> None:
    brief = cli_help_brief()
    full = cli_help_text()
    assert "kite run" in brief and "kite help all" in brief
    assert "kite keys" not in brief
    assert "kite keys" in full
    assert "interactive session" in CLI_EPILOG


def test_cli_parser_hides_secondary_commands() -> None:
    parser = build_parser()
    help_text_cli = parser.format_help()
    for name in ("run", "resume", "setup", "sessions", "tasks", "help"):
        assert f"  {name}" in help_text_cli
    for hidden in ("models", "chat", "exec", "maintainer", "config", "bench"):
        assert f"  {hidden} " not in help_text_cli
    assert parser.parse_args(["chat"]).command == "chat"
    assert parser.parse_args(["exec", "task"]).command == "exec"
    assert parser.parse_args(["help", "all"]).topic == "all"


def test_repl_help_primary_vs_all() -> None:
    index = CommandIndex.load(".")
    brief = help_text(index)
    full = help_text(index, all=True)
    assert "/plan" in brief and "/build" in brief
    assert "More: /help all" in brief
    assert "/compact" not in brief
    assert "/select" not in brief
    assert "/compact" in full
    assert "/select" in full
    primary = primary_builtins()
    assert len(primary) == 12
    assert primary[0].name == "build"
    assert primary[1].name == "plan"


def test_legacy_slash_still_dispatches() -> None:
    assert parse_slash("/compact").command == "compact"
    assert parse_slash("/thinking").command == "reasoning"
    assert parse_slash("/cost").command == "status"
    assert not is_primary_slash("compact")
    assert is_primary_slash("plan")


def test_completion_hides_advanced_aliases() -> None:
    index = CommandIndex.load(".")
    from kite.models.reasoning import ReasoningSupport

    support = ReasoningSupport(False, False, False, False, source="none")
    names = {spec.name for spec in _visible_specs(index, support=support)}
    assert "plan" in names and "model" in names
    assert "compact" not in names
    assert "cost" not in names
    assert "explain" not in names

    completer = SlashCompleter(lambda: index)
    completions = list(
        completer.get_completions(
            type("D", (), {"text_before_cursor": "/"})(),
            None,
        )
    )
    completion_names = {c.text for c in completions}
    assert "plan" in completion_names
    assert "compact" not in completion_names


def test_status_footer_modes() -> None:
    idle = SessionUiState(mode=AgentMode.BUILD, provider="groq", model="llama", cost=0.02)
    segments = status_segments(idle)
    texts = [t for t, _ in segments]
    assert texts == ["build", "groq/llama", "$0.020"]

    busy = SessionUiState(mode=AgentMode.BUILD, provider="groq", model="llama", cost=0.02, busy=True)
    busy.running_label = "pytest tests/"
    segments = status_segments(busy)
    assert segments[1][0] == "pytest tests/"

    approval = SessionUiState(awaiting_approval="bash", awaiting_approval_mandatory=True)
    segments = status_segments(approval)
    assert segments[0][0] == "approval"


def test_status_render_terminal_widths() -> None:
    state = SessionUiState(mode=AgentMode.PLAN, provider="groq", model="llama-3.3-70b", cost=0.01)
    for width in (50, 80, 120):
        buf = StringIO()
        console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
        console.print(render_status(state))
        plain = strip_ansi(buf.getvalue())
        assert "kite" in plain and "plan" in plain and "$0.010" in plain
