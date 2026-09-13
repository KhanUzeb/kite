"""Minimal CLI / REPL surface — progressive disclosure."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.mode import AgentMode
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


def test_cli_parser_lists_usable_commands() -> None:
    parser = build_parser()
    help_text_cli = parser.format_help()
    for name in ("run", "resume", "setup", "sessions", "tasks", "help", "models", "chat", "exec", "config", "bench"):
        assert name in help_text_cli
    assert "maintainer" not in help_text_cli
    assert parser.parse_args(["chat"]).command == "chat"
    assert parser.parse_args(["exec", "task"]).command == "exec"
    assert parser.parse_args(["help", "all"]).topic == "all"
    assert parser.parse_args(["-c"]).continue_last is True
    assert parser.parse_args(["-r"]).resume_pick is True


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
    assert len(primary) == 13
    assert primary[0].name == "build"
    assert primary[1].name == "plan"
    assert any(b.name == "thinking" for b in primary)


def test_legacy_slash_still_dispatches() -> None:
    assert parse_slash("/compact").command == "compact"
    assert parse_slash("/thinking").command == "thinking"
    assert parse_slash("/reasoning").command == "reasoning"
    assert parse_slash("/fast").command == "thinking"
    assert parse_slash("/fast").legacy == "fast"
    assert parse_slash("/cost").command == "status"
    assert not is_primary_slash("compact")
    assert is_primary_slash("plan")


def test_completion_lists_commands_and_skills_with_cues() -> None:
    index = CommandIndex.load(".")
    from kite.models.reasoning import ReasoningSupport
    from kite.ui.complete import _slash_display, _slash_meta, _slash_origin

    support = ReasoningSupport(False, False, False, False, source="none")
    specs = _visible_specs(index, support=support)
    names = {spec.name for spec in specs}
    assert "plan" in names and "model" in names
    assert "compact" in names
    assert "explain" in names
    assert "commit" in names
    assert "cost" not in names

    origins = {_slash_origin(s, index) for s in specs}
    assert "builtin" in origins
    assert "prompt-bundled" in origins
    assert "skill-bundled" in origins

    plan = next(s for s in specs if s.name == "plan")
    explain = next(s for s in specs if s.name == "explain")
    commit = next(s for s in specs if s.name == "commit")
    assert _slash_display(plan, index).startswith("· /plan")
    assert _slash_display(explain, index).startswith("▸ /explain")
    assert _slash_display(commit, index).startswith("◆ /commit")
    assert _slash_meta(plan, index).startswith("cmd")
    assert "prompt" in _slash_meta(explain, index)
    assert _slash_meta(commit, index).startswith("skill")

    completer = SlashCompleter(lambda: index)
    completions = list(
        completer.get_completions(
            type("D", (), {"text_before_cursor": "/"})(),
            None,
        )
    )
    completion_names = {c.text for c in completions}
    assert "plan" in completion_names
    assert "compact" in completion_names
    assert "explain" in completion_names
    assert "commit" in completion_names
    assert "tools" in names


def test_composer_mouse_defaults_off() -> None:
    import os

    from kite.ui.complete import _mouse_support_enabled

    prev = os.environ.get("KITE_MOUSE")
    os.environ.pop("KITE_MOUSE", None)
    try:
        assert _mouse_support_enabled() is False
        os.environ["KITE_MOUSE"] = "1"
        assert _mouse_support_enabled() is True
    finally:
        if prev is None:
            os.environ.pop("KITE_MOUSE", None)
        else:
            os.environ["KITE_MOUSE"] = prev


def test_builtin_tool_catalog_cues() -> None:
    from kite.tools.cues import format_tool_catalog, tool_cue
    from kite.ui.tool_cards import ToolCard, render_tool_card_done, render_tool_card_start

    assert tool_cue("read") == ("○", "read")
    assert tool_cue("edit") == ("✎", "edit")
    assert tool_cue("bash") == ("$", "sh")
    assert tool_cue("websearch") == ("↗", "net")
    assert tool_cue("subagent") == ("◈", "crew")
    catalog = format_tool_catalog()
    assert "○ read" in catalog
    assert "$ bash" in catalog
    assert "◈ subagent" in catalog
    start = render_tool_card_start(ToolCard(tool="grep", detail="foo"), running=False).plain
    assert "○" in start and "grep" in start and "read" in start
    done = render_tool_card_done("write", ok=True).plain
    assert "✎" in done and "write" in done and "edit" in done


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
