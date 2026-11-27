"""Minimal CLI / REPL surface — progressive disclosure."""

from __future__ import annotations

from io import StringIO

from prompt_toolkit.document import Document
from rich.cells import cell_len
from rich.console import Console

from kite.agent.mode import AgentMode
from kite.cli.help_map import cli_help_brief, cli_help_text
from kite.cli.run import build_parser
from kite.cli.slash import CommandIndex, help_text
from kite.ui.commands import is_primary_slash, parse_slash
from kite.ui.complete import SlashCompleter, _visible_specs
from kite.ui.state import SessionUiState
from kite.ui.status import render_status, status_segments
from kite.ui.style import KITE_THEME
from tests.conftest import strip_ansi


def test_cli_help_and_parser_lists_usable_commands(kite_home) -> None:
    brief = cli_help_brief()
    full = cli_help_text()
    assert "kite run" in brief and "kite help all" in brief
    assert "kite keys" not in brief
    assert "kite keys" in full
    parser = build_parser()
    help_text_cli = parser.format_help()
    for name in ("run", "resume", "setup", "sessions", "tasks", "help", "models", "chat", "exec", "config", "bench", "theme", "font", "variant", "variants"):
        assert name in help_text_cli
    assert "maintainer" not in help_text_cli
    assert parser.parse_args(["chat"]).command == "chat"
    assert parser.parse_args(["exec", "task"]).command == "exec"
    assert parser.parse_args(["help", "all"]).topic == "all"
    assert parser.parse_args(["-c"]).continue_last is True
    assert parser.parse_args(["-r"]).resume_pick is True


def test_repl_help_and_legacy_slash_dispatch(workspace, kite_home) -> None:
    index = CommandIndex.load(workspace)
    brief = help_text(index)
    full = help_text(index, all=True)
    assert "/plan" in brief and "/build" in brief
    assert "More: /help all" in brief
    assert "/compact" not in brief
    assert "/select" not in brief
    assert "/compact" in full
    assert "/select" in full
    assert parse_slash("/fast").command == "variant"
    assert parse_slash("/fast").legacy == "fast"
    for retired in ("/variants", "/thinking", "/reasoning", "/effort"):
        assert parse_slash(retired).command == "variant"
        assert parse_slash(retired).legacy == ""
    assert parse_slash("/cost").command == "status"
    assert not is_primary_slash("compact")
    assert is_primary_slash("plan")

    from kite.ui.repl import ChatSession

    chat = object.__new__(ChatSession)
    chat._index = lambda: index
    for width in (50, 80, 120):
        for arg in ("", "all"):
            buf = StringIO()
            chat.console = Console(file=buf, width=width, height=24, theme=KITE_THEME, soft_wrap=True)
            chat._slash_help(arg)
            chat._slash_hotkeys("")
            rows = strip_ansi(buf.getvalue()).splitlines()
            assert all(cell_len(row) <= width for row in rows), (width, arg, rows)
            assert any("/theme" in row for row in rows)
            assert any("Ctrl+C" in row for row in rows)


def test_completion_cues_and_variants_when_reasoning_is_unavailable(workspace, kite_home) -> None:
    from kite.models.reasoning import ReasoningSupport
    from kite.ui.complete import _slash_display, _slash_meta, _slash_origin

    index = CommandIndex.load(workspace)
    support = ReasoningSupport(False, False, False, False, source="none")
    specs = _visible_specs(index, support=support)
    names = {spec.name for spec in specs}
    assert "plan" in names and "model" in names
    assert "compact" in names
    assert "explain" in names
    assert "commit" in names
    assert "cost" not in names
    assert "variant" in names
    for retired in ("variants", "thinking", "reasoning", "effort", "fast"):
        assert retired not in names

    origins = {_slash_origin(s, index) for s in specs}
    assert "builtin" in origins
    assert "prompt-bundled" in origins
    assert "skill-bundled" in origins

    plan = next(s for s in specs if s.name == "plan")
    explain = next(s for s in specs if s.name == "explain")
    commit = next(s for s in specs if s.name == "commit")
    assert _slash_display(plan, index) == "/plan"
    assert _slash_display(explain, index).startswith("▸ /explain")
    assert _slash_display(commit, index).startswith("◆ /commit")
    assert _slash_meta(plan, index).startswith("Opt-in read-only")
    assert _slash_meta(explain, index).startswith("Explain the repo")
    assert not any(_slash_meta(spec, index).startswith(tag) for spec in specs for tag in ("cmd", "prompt", "skill"))

    def unavailable_reasoning_info():
        raise RuntimeError("reasoning support is not ready")

    bare_completer = SlashCompleter(lambda: index, reasoning_info=unavailable_reasoning_info)
    bare_completions = list(
        bare_completer.get_completions(
            Document("/"),
            None,
        )
    )
    completion_names = {completion.text for completion in bare_completions}
    assert {"model", "plan", "compact", "explain", "commit", "tools"} <= completion_names
    assert "variant" in completion_names
    # Retired names and the /fast shortcut stay parseable but must not crowd
    # the bare-slash menu; the unified command is the only one discoverable.
    assert {"variants", "thinking", "reasoning", "effort", "fast"}.isdisjoint(completion_names)
    assert {c.text for c in bare_completer.get_completions(Document("/var"), None)} == {"variant"}
    assert {c.text for c in bare_completer.get_completions(Document("/reas"), None)} == set()

    for typed in ("/variant ", "/variants ", "/fast "):
        args = {
            completion.text
            for completion in bare_completer.get_completions(Document(typed), None)
        }
        assert {"off", "low", "medium", "high"} <= args


def test_hidden_retired_aliases_are_not_suggested(workspace, kite_home) -> None:
    """Did-you-mean must offer discoverable commands, not hidden aliases."""
    from kite.cli.slash import CommandIndex, resolve_slash

    index = CommandIndex.load(workspace)
    for typo, hidden in (
        ("/thinkng", "/thinking"),
        ("/reasong", "/reasoning"),
        ("/varaints", "/variants"),
        ("/fats", "/fast"),
    ):
        message = resolve_slash(typo, index).message
        assert hidden not in message
        assert "did you mean" in message or "type /help" in message
    # Visible commands still get the normal suggestion.
    assert "did you mean '/status'?" in resolve_slash("/staus", index).message
    assert "did you mean '/variant'?" in resolve_slash("/varaints", index).message


def test_status_footer_modes() -> None:
    idle = SessionUiState(mode=AgentMode.BUILD, provider="groq", model="llama", cost=0.02)
    segments = status_segments(idle)
    texts = [t for t, _ in segments]
    assert texts == ["build", "groq/llama", "$0.020"]

    busy = SessionUiState(mode=AgentMode.BUILD, provider="groq", model="llama", cost=0.02, busy=True)
    busy.running_label = "pytest tests/"
    segments = status_segments(busy)
    assert [text for text, _ in segments] == ["build", "groq/llama", "$0.020"]

    approval = SessionUiState(awaiting_approval="bash", awaiting_approval_mandatory=True)
    segments = status_segments(approval)
    assert segments[0][0] == "approval"


def test_running_status_truncation_and_terminal_widths(monkeypatch) -> None:
    import os
    import shutil

    from kite.ui.status import format_running_status

    state = SessionUiState(busy=True)
    state.running_label = "x" * 200
    state.running_since = "12:00:00"
    state.activity_preview = "y" * 200

    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda fallback=None: os.terminal_size((50, 24))
    )
    narrow = format_running_status(state)
    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda fallback=None: os.terminal_size((200, 24))
    )
    wide = format_running_status(state)
    assert len(narrow) < len(wide)
    assert narrow.endswith("…") or "›" in narrow

    render_state = SessionUiState(mode=AgentMode.PLAN, provider="groq", model="llama-3.3-70b", cost=0.01)
    for width in (50, 80, 120):
        buf = StringIO()
        console = Console(file=buf, width=width, force_terminal=True, theme=KITE_THEME)
        console.print(render_status(render_state))
        plain = strip_ansi(buf.getvalue())
        assert "kite" in plain and "plan" in plain and "$0.010" in plain
        assert all(cell_len(row) <= width for row in plain.splitlines())
