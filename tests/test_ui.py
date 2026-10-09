"""REPL, render, theme, composer, attach, preview, privacy."""

from __future__ import annotations

import re
from contextlib import nullcontext
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from kite.agent.events import Event
from kite.agent.mode import AgentMode, ApprovalMode
from kite.agent.queue import RunMessageQueue
from kite.application.policy import ApprovalCoordinator
from kite.config.user import UserConfig
from kite.memory.session_policy import persistence_summary, set_persistence_mode
from kite.ui.attach import (
    Attachment,
    clipboard_install_hint,
    load_clipboard,
    parse_inline_mentions,
    read_clipboard_text,
    user_content_with_attachments,
)
from kite.ui.complete import make_repl_key_bindings, read_repl_line
from kite.ui.diff import (
    PREVIEW_NOT_APPLIED,
    count_diff_lines,
    make_unified_diff,
    preview_mutating_diff,
    preview_patch_diff,
    preview_write_diff,
    render_diff,
)
from kite.ui.empty import render_empty
from kite.ui.render import RunDisplay
from kite.ui.repl import ChatSession
from kite.ui.state import SessionUiState
from kite.ui.status import format_status_tail, render_status, status_segments
from kite.ui.style import KITE_THEME
from kite.ui.theme import (
    THEME_NAMES,
    palette,
    pt_style_dict,
    resolved_theme,
    set_theme,
)
from kite.ui.tool_cards import render_code_edit_preview
from tests.conftest import strip_ansi


@pytest.fixture(autouse=True)
def _isolated_ui_state(monkeypatch, kite_home, tmp_path):
    from kite.ui import git, theme

    monkeypatch.setattr(theme, "_prefs", replace(theme._prefs, theme="auto", font="unicode"))
    monkeypatch.setattr(theme, "_loaded", True)
    for cache in ("_repo_cache", "_status_cache", "_branch_cache"):
        monkeypatch.setattr(git, cache, {})
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.setattr("kite.models.litellm_model.prewarm_litellm", lambda: None)
    monkeypatch.setattr(ChatSession, "_warm_auth_probes", lambda self: None)


@pytest.fixture
def reasoning_support():
    from kite.models.reasoning import ReasoningSupport

    return ReasoningSupport(
        supported=True,
        can_fast=True,
        can_thinking=True,
        can_disable=True,
        thinking_kwargs={"reasoning_effort": "high"},
        fast_kwargs={"reasoning_effort": "low"},
        efforts=("none", "low", "medium", "high"),
    )


def test_render_events_busy_spin_and_quiet_tools() -> None:
    buf = StringIO()
    display = RunDisplay(Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME), state=SessionUiState(), quiet=False)
    display.state.busy = True
    display(Event("cost_estimate", payload={"cost_limit": 5.0, "note": "Budget: ≤$5.00"}))
    assert display.state.budget_limit == 5.0
    display.state.busy = False
    display(Event("tool_end", payload={"tool": "bash", "ok": False, "error": "Command failed\nline two\nline three"}))
    assert "line two" in buf.getvalue()
    display(Event("compact", payload={"before": 42, "after": 12, "total_tokens": 24_000, "window": 128_000}))
    assert display.state.tokens == 24_000 and "42 → 12" in buf.getvalue()
    display(Event("submit_blocked", payload={"reason": "tests not run"}))
    assert "submit blocked" in strip_ansi(buf.getvalue()).lower()
    display(Event("agent_end", payload={"exit_status": "LimitsExceeded", "content": "step budget 40/40", "limit_kind": "steps", "steps": 40, "step_limit": 40, "tools": 2, "duration_ms": 1400, "n_calls": 3, "cost": 0.02}))
    assert "continue" in buf.getvalue().lower()
    assert "2 tools" in strip_ansi(buf.getvalue())
    display.state.busy = True
    display._spin(True, "thinking")
    assert display._spinner_on is False and display.state.running_label == "thinking"

    quiet = StringIO()
    inspect_display = RunDisplay(Console(file=quiet, width=120, force_terminal=True, theme=KITE_THEME), state=SessionUiState())
    inspect_display(Event("tool_start", payload={"tool": "read", "arguments": {"path": "src/kite/cli/run.py"}}))
    inspect_display(Event("tool_end", payload={"tool": "read", "ok": True, "preview": "ok", "output": "line\n"}))
    plain = strip_ansi(quiet.getvalue())
    assert "running" not in plain
    assert "read" in plain


def test_spinner_heartbeats_when_stderr_is_not_a_tty(monkeypatch) -> None:
    from kite.ui import spinner as spinner_mod

    monkeypatch.setattr(spinner_mod, "os_environ_pytest", lambda: False)
    buf = StringIO()
    sp = spinner_mod.WaitSpinner(buf, heartbeat_s=0.1, label="working  bash")
    waits = []

    def wait(interval):
        waits.append(interval)
        return len(waits) == 4

    class InlineThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

        def is_alive(self):
            return False

    monkeypatch.setattr(sp._stop, "wait", wait)
    monkeypatch.setattr(spinner_mod.threading, "Thread", InlineThread)
    try:
        sp.start()
        out = buf.getvalue()
        assert out.count("working  bash") == 3
        assert "\r" not in out, "carriage returns corrupt piped/relayed logs"
        assert waits == [0.1, 0.2, 0.4, 0.8]
        assert sp._shown is False, "nothing to erase on a non-TTY stream"
    finally:
        sp.stop()


def test_turn_stays_visibly_alive_between_events() -> None:
    """No dead windows: the answer tail and the next model call both show up.

    A REPL turn that buffers the answer and leaves the spinner off between a
    finished tool and the next generation reads as a hang while work continues.
    """
    buf = StringIO()
    display = RunDisplay(Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME))
    display.composer_owns_input = True  # REPL streams through patch_stdout live
    display(Event("stream_delta", payload={"text": "Reading src/kite/agent/loop.py"}))
    assert "Reading src/kite/agent" in display.state.activity_preview
    # The answer paints during the turn rather than being deferred to teardown.
    assert "Reading src/kite/agent/loop.py" in strip_ansi(buf.getvalue())

    display(Event("tool_end", payload={"tool": "read", "ok": True, "preview": "ok", "output": "x\n"}))
    assert display._spinner_on is True, "a finished tool hands the spinner to the next call"
    display.close()

    # With the composer owning the bottom, the footer carries the label instead.
    footer = RunDisplay(Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME))
    footer.state.busy = True
    footer(Event("tool_end", payload={"tool": "read", "ok": True, "preview": "ok", "output": "x\n"}))
    assert footer.state.running_label == "thinking"
    footer.close()


def test_output_and_thinking_unwrap_full_width() -> None:
    from kite.ui.output_view import (
        format_thinking_text,
        format_viewable_output,
        render_output_block,
        render_thinking_block,
    )
    from kite.ui.render import _collapse_text, render_reasoning_block

    envelope = '{"ok": true, "output": "hello\\nworld"}'
    assert format_viewable_output(envelope) == "hello\nworld\n"
    nested = '{"ok": true, "output": "{\\"n\\": 1}"}'
    assert '"n": 1' in format_viewable_output(nested)
    assert format_viewable_output("plain line") == "plain line"
    block = render_output_block(envelope, expanded=True)
    assert "hello" in block.plain and "{" not in block.plain
    collapsed = _collapse_text(envelope, expanded=True)
    assert collapsed.plain.startswith("hello")

    blob = '{"reasoning": "check the tests first"}'
    assert format_thinking_text(blob).strip() == "check the tests first"
    wrapped = '{"ok": true, "output": "look at grep"}'
    assert "look at grep" in format_thinking_text(wrapped)
    think_block = render_thinking_block(blob)
    assert think_block.plain.startswith("check the tests first")
    assert not think_block.plain.startswith("…")
    shown = render_reasoning_block(blob)
    assert "check the tests first" in shown.plain
    assert shown.plain.find("check") < 8


def _render_card(
    width: int,
    *,
    provider: str = "chatgpt",
    model: str = "gpt-5.6-luna",
    workspace: str = "kite",
    context: list[str] | None = None,
) -> str:
    from kite.ui.render import render_startup_card

    buf = StringIO()
    # Rich ≥15 only honors an explicit width when height is set too.
    Console(file=buf, width=width, height=40, theme=KITE_THEME).print(
        render_startup_card(
            version="0.9.8.5",
            provider=provider,
            model=model,
            workspace=workspace,
            context_files=list(context or []),
            compact=width < 60,
        )
    )
    return strip_ansi(buf.getvalue())


def test_startup_card_width_truncation_and_context() -> None:
    wide = _render_card(100, context=["AGENTS.md"])
    for token in (
        "🪁 Kite 0.9.8.5",
        "chatgpt/gpt-5.6-luna",
        "build",
        "kite",
        "AGENTS.md",
        "/help",
        "/model",
        "@file",
    ):
        assert token in wide, token
    assert "inspecting, editing, and verifying" in wide

    # Narrow terminals shorten the blurb instead of rewrapping the wide one.
    narrow = _render_card(50)
    assert "for your terminal." in narrow
    assert "inspecting, editing, and verifying" not in narrow
    for line in narrow.splitlines():
        assert len(line) <= 50

    # Missing configuration renders an em dash, not an empty field.
    assert "—/gpt-5.6-luna" in _render_card(100, provider="—")

    long_model = "a-very-long-model-id-that-keeps-going-and-going-xyz"
    card = _render_card(100, provider="openrouter", model=long_model)
    assert "…" in card and "a-very-long-model-id" in card and long_model not in card
    assert "…" not in _render_card(100)
    many = _render_card(100, context=["a.md", "b.md", "c.md", "d.md", "e.md"])
    assert "+2 more" in many and "a.md" in many and "e.md" not in many
    narrow_long = _render_card(
        50, provider="openrouter", model=long_model, workspace="a-deeply-nested-workspace-name-that-overflows"
    )
    for line in narrow_long.splitlines():
        assert len(line) <= 50

    line = next(
        ln for ln in _render_card(100, provider="groq", model="llama", workspace="demo").splitlines()
        if "groq/llama" in ln
    )
    # No dangling separator: the workspace is the last field on the line.
    assert "demo" in line and "demo ·" not in line
    assert line.split("demo", 1)[1].strip(" │") == ""


def test_theme_palettes_and_status() -> None:
    assert set_theme("glass") == "transparent"
    transparent = pt_style_dict("transparent")
    assert "bg:default" in transparent["bottom-toolbar"]
    assert "bg:default" in transparent["composer"]
    assert set_theme("catpuccin") == "catppuccin"
    assert resolved_theme("catpuccin") == "catppuccin"
    for name in THEME_NAMES:
        ui = palette(name)["ui"]
        assert ui.completion_current_bg == ui.completion_bg
    state = SessionUiState(mode=AgentMode.PLAN, approval=ApprovalMode.READONLY, model="llama", provider="groq")
    tail = format_status_tail(state)
    rendered = render_status(state).plain
    for token in ("plan", "groq/llama", "$0.000"):
        assert token in tail and token in rendered
    assert "/kill all" in render_empty("no jobs", hint="/kill all").plain


def test_composer_interrupt_kinds_aliases_and_empty(monkeypatch, workspace, kite_home) -> None:
    monkeypatch.setattr("prompt_toolkit.patch_stdout.patch_stdout", lambda raw=False: nullcontext())
    session = MagicMock()
    session.prompt.side_effect = KeyboardInterrupt()
    session.default_buffer.text = ""
    assert read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None).kind == "empty"
    session.default_buffer.text = "use grep not find"
    steered = read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None, busy=True)
    assert steered.kind == "steer" and steered.text == "use grep not find"
    session.default_buffer.text = ""
    assert read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None, busy=True).kind == "stop"
    session.prompt.side_effect = EOFError()
    assert read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None).kind == "eof"
    q = RunMessageQueue()
    q.enqueue("later")
    q.steer("now")
    assert q.counts() == (1, 1) and q.drain_all() == [("now", True), ("later", False)]
    assert set_persistence_mode("disabled") == "disabled"
    assert UserConfig.load().session_persistence == "disabled"
    set_persistence_mode("redacted")
    summary = persistence_summary()
    assert "ssrf" in summary and summary["session_persistence"] == "redacted"

    from kite.cli.slash import CommandIndex, resolve_slash
    from kite.ui.complete import classify_busy_line

    parsed = resolve_slash("/exit", CommandIndex.load(workspace))
    assert parsed.command == "quit"
    assert classify_busy_line("/exit").kind == "eof"

    got = read_repl_line(session=None, state=SessionUiState(), fallback=lambda: "   ")
    assert got.kind == "empty"


def test_live_streaming_paints_once_and_interrupt_is_quiet() -> None:
    """The turn must look alive, and never repeat itself."""
    buf = StringIO()
    display = RunDisplay(Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME))
    display.composer_owns_input = True
    display(Event("agent_start", payload={"task": "fix the auth race"}))
    for piece in ("Root cause was ", "a race in ", "the auth middleware."):
        display(Event("stream_delta", payload={"text": piece}))
    display(Event("stream_end", payload={}))
    painted = strip_ansi(buf.getvalue())
    assert "Root cause was a race in the auth middleware." in painted, "tokens must reach the screen"

    display(
        Event(
            "agent_end",
            payload={"exit_status": "Submitted", "submission": "## Done\n- Fixed the race"},
        )
    )
    display.finish_composer_turn()
    final = strip_ansi(buf.getvalue())
    assert final.count("Root cause was a race in the auth middleware.") == 1
    assert final.count("Fixed the race") == 1, "the report is surfaced exactly once"
    display.close()

    # Several cancel paths can emit interrupt; the user sees one line.
    stops = StringIO()
    quiet = RunDisplay(Console(file=stops, width=80, force_terminal=True, theme=KITE_THEME))
    quiet(Event("agent_start", payload={"task": "long task"}))
    for _ in range(4):
        quiet(Event("interrupt", payload={"reason": "esc"}))
    assert strip_ansi(stops.getvalue()).count("stopped") == 1
    quiet.close()

    # Ending the agent without stream_end must flush a short trailing chunk.
    buf = StringIO()
    display = RunDisplay(Console(file=buf, width=80, theme=KITE_THEME))
    display(Event("agent_start", payload={"task": "hi"}))
    display(Event("stream_delta", payload={"text": "all done"}))
    display(Event("agent_end", payload={"exit_status": "Submitted", "submission": "all done"}))
    assert "all done" in strip_ansi(buf.getvalue())
    display.close()


def test_repl_lazy_slash_and_jobs(monkeypatch, tmp_path, kite_home) -> None:
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **_: MagicMock(provider="groq", model="llama-test"))
    session = ChatSession(cwd=str(tmp_path))
    assert session._handle_slash("/quit") is False
    assert session._handle_slash("/plan") is True
    assert session.state.mode is AgentMode.PLAN and session.state.approval is ApprovalMode.READONLY
    assert session._handle_slash("/restricted on") is True
    session._pick = lambda items, **kw: "yolo"  # type: ignore[method-assign]
    assert session._handle_slash("/approve") is True
    assert session.state.approval is ApprovalMode.YOLO

    @dataclass
    class _FakeJob:
        id: str
        kind: str = "bash"
        command: str = "sleep 1"
        label: str = ""
        pid: int | None = 4242
        status: str = "running"

        def display_label(self, *, width: int = 48) -> str:
            return self.command[:width]

    class _FakeRegistry:
        def __init__(self) -> None:
            job = _FakeJob(id="bash0001", command="npm run dev")
            self.killed: list[str] = []
            self._map = {job.id: job}

        def list(self, *, active_only: bool = True):
            return [j for j in self._map.values() if j.status == "running"]

        def active_count(self) -> int:
            return len(self.list())

        def kill(self, job_id: str) -> bool:
            job = self._map[job_id]
            job.status = "killed"
            self.killed.append(job_id)
            return True

        def kill_all(self) -> int:
            n = 0
            for job in self._map.values():
                if job.status == "running":
                    job.status = "killed"
                    n += 1
            return n

    session.jobs = _FakeRegistry()  # type: ignore[assignment]
    session._pick = lambda items, **kw: "bash0001"  # type: ignore[method-assign]
    assert session._handle_slash("/jobs") is True
    assert session.jobs.killed == ["bash0001"]  # type: ignore[attr-defined]
    session.jobs = _FakeRegistry()  # type: ignore[assignment]
    assert session._handle_slash("/kill all") is True
    assert session.jobs.active_count() == 0
    session.jobs = _FakeRegistry()  # type: ignore[assignment]
    session._teardown_jobs()
    assert session.jobs.active_count() == 0
    calls: list[dict] = []
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **kwargs: calls.append(kwargs) or (_ for _ in ()).throw(AssertionError("no resolve")))
    ChatSession(cwd=str(tmp_path))
    assert not calls
    resolved = MagicMock(provider="groq", model="llama-test")
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **_: resolved)
    live = ChatSession(cwd=str(tmp_path))
    live._ensure_model_resolved()
    assert live._make_harness() is live._make_harness()
    repl = ChatSession(cwd=str(tmp_path), provider="fake", model="fake")
    repl._approval_coordinator = ApprovalCoordinator(interactive=True)
    repl._approval_coordinator._pending = MagicMock(tool="bash", request_id="r1", mandatory=True)
    repl._poll_pending_approval()
    assert repl.state.awaiting_approval == "bash"


def test_attach_clipboard_and_diff_helpers(tmp_path, kite_home, monkeypatch) -> None:
    note = tmp_path / "note.txt"
    note.write_text("hello attach", encoding="utf-8")
    task, found = parse_inline_mentions(f"please fix @{note.name}", tmp_path)
    assert found and found[0].name == "note.txt"
    att = Attachment(kind="text", name="clip.txt", source="clipboard", text="secret paste")
    packed = user_content_with_attachments("review this", [att], images=False)
    assert "source: clipboard" in packed and "secret paste" in packed
    payload = tmp_path / "payload.txt"
    payload.write_text("file body", encoding="utf-8")
    with patch("kite.ui.attach._clipboard_text", return_value=str(payload)):
        with patch("kite.ui.attach._clipboard_image_posix", return_value=None):
            with patch("kite.ui.attach._clipboard_image_windows", return_value=None):
                clip = load_clipboard()
    assert "file body" in clip.text
    monkeypatch.setattr("kite.ui.attach.shutil.which", lambda _: None)
    monkeypatch.setattr("kite.ui.attach.os.name", "posix")
    hint = clipboard_install_hint()
    assert "xclip" in hint or "wl-clipboard" in hint
    added, deleted = count_diff_lines(make_unified_diff("src/foo.py", "a\nb\nc\n", "a\nB\nc\nD\n"))
    assert added == 2 and deleted == 1
    big = tmp_path / "big.py"
    big.write_text("prefix\nneedle\nsuffix\n" + ("x" * 100_000))
    original = Path.read_text

    def spy_read_text(self: Path, *args, **kwargs) -> str:
        if self == big:
            raise AssertionError("preview should not read the entire large file")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    preview = preview_mutating_diff("edit", big, {"path": str(big), "old": "needle", "new": "found"}, cwd=tmp_path)
    assert "-needle" in preview and "+found" in preview

    unified = make_unified_diff("src/a.py", "line one\n", "line two\n")
    rendered = render_diff(unified, collapsed=True).plain
    assert "src/a.py" in rendered
    assert "+1" in rendered and "-1" in rendered
    assert "line two" in rendered and "line one" in rendered
    preview_card = render_code_edit_preview(
        "edit",
        {"path": "lib/x.py", "old": "foo", "new": "bar"},
    )
    assert preview_card is not None
    assert "lib/x.py" in preview_card.plain
    assert "foo" in preview_card.plain and "bar" in preview_card.plain


def test_preview_builders_carry_not_applied_banner(tmp_path) -> None:
    patch = preview_patch_diff("src/foo.py", "old line\n", "new line\n")
    assert patch.startswith(PREVIEW_NOT_APPLIED)
    assert "-old line" in patch and "+new line" in patch
    write = preview_write_diff("src/new.py", "hello\n", existing_bytes=None)
    assert write.startswith(PREVIEW_NOT_APPLIED)
    target = tmp_path / "code.py"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    shown = preview_mutating_diff(
        "edit", target, {"path": str(target), "old": "beta", "new": "BETA"}, cwd=tmp_path
    )
    assert shown.startswith(PREVIEW_NOT_APPLIED)
    assert shown.count(PREVIEW_NOT_APPLIED) == 1
    assert "-beta" in shown and "+BETA" in shown
    # Banner line is not a +/- row: numstat-style counts are unchanged.
    assert count_diff_lines(shown) == (1, 1)
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"
    rendered = render_diff(shown).plain
    assert PREVIEW_NOT_APPLIED in rendered


def test_render_diff_shows_old_new_line_numbers() -> None:
    from kite.ui.diff import _line_numbers

    diff = make_unified_diff(
        "src/app.py",
        "def f():\n    return 1\n\n\ndef g():\n    pass\n",
        "def f(a, b):\n    total = a + b\n    return total\n\n\ndef g():\n    pass\n",
    )
    plain = render_diff(diff).plain
    # Context advances both counters; an added line has no old number.
    assert "  3 4 " in plain and "  5 6 " in plain
    assert "  1   " in plain, "the paired -/+ lines carry their own numbers"
    assert "  1 ┊ +" in plain
    # Meta and hunk rows keep the left edge instead of blank number columns.
    meta = [ln for ln in plain.splitlines() if any(t in ln for t in ("--- a/", "+++ b/", "@@ -"))]
    assert meta and all(ln.lstrip().startswith("┊") for ln in meta)

    assert _line_numbers(["@@ -10,3 +20,2 @@", "-a", "+b", " ctx"])[1:] == [
        (10, None),
        (None, 20),
        (11, 21),
    ]


def test_render_diff_word_highlights_mixed_indent() -> None:
    diff = make_unified_diff("x.py", "\tfoo bar\n", "  foo BAZ\n")
    body = render_diff(diff)
    plain = body.plain
    assert "→" in plain and "·" in plain
    assert "BAZ" in plain and "foo" in plain
    changed = [s.style for s in body.spans if "BAZ" in plain[s.start : s.end]]
    assert changed and all("reverse" in str(s) for s in changed)
    calm = [s.style for s in body.spans if "foo" in plain[s.start : s.end]]
    assert calm and all("reverse" not in str(s) for s in calm)
    # Line-level behavior otherwise identical: unpaired/context lines still render.
    ctx = render_diff(make_unified_diff("x.py", "keep\nold\n", "keep\nnew\n")).plain
    assert "keep" in ctx and "old" in ctx and "new" in ctx


def _bindings_by_handler(bindings, name: str):  # noqa: ANN001, ANN202
    return [b for b in bindings.bindings if getattr(b.handler, "__name__", "") == name]


def _fake_composer_event():  # noqa: ANN202
    from types import SimpleNamespace

    from prompt_toolkit.buffer import Buffer

    return SimpleNamespace(current_buffer=Buffer(), app=MagicMock())


def test_ctrl_v_pastes_text_or_attaches_screenshot() -> None:
    slot: dict = {}
    attached: list[str] = []
    bindings = make_repl_key_bindings(
        on_attach_clipboard=lambda: attached.append("clip") or "attached clip.png (image)",
        action_slot=slot,
    )
    (paste_binding,) = [b for b in _bindings_by_handler(bindings, "_paste") if "ControlV" in str(b.keys)]

    event = _fake_composer_event()
    with patch("kite.ui.attach.read_clipboard_text", return_value="hello\r\nworld"):
        paste_binding.handler(event)
    assert event.current_buffer.text == "hello\nworld"
    assert attached == []

    event = _fake_composer_event()
    with patch("kite.ui.attach.read_clipboard_text", return_value=""):
        paste_binding.handler(event)
    assert attached == ["clip"]
    assert slot.get("kind") == "note"
    event.app.invalidate.assert_called()
    assert event.current_buffer.text == ""


def test_ctrl_c_copies_selection_without_stopping() -> None:
    bindings = make_repl_key_bindings()
    matches = _bindings_by_handler(bindings, "_copy_selected")
    assert len(matches) == 1
    event = _fake_composer_event()
    event.current_buffer.text = "selected"
    event.current_buffer.cursor_position = 0
    event.current_buffer.start_selection()
    event.current_buffer.cursor_position = len(event.current_buffer.text)
    with patch("kite.ui.attach.write_os_clipboard") as writer:
        matches[0].handler(event)
    writer.assert_called_once_with("selected")
    assert event.current_buffer.text == "selected"
    event.app.exit.assert_not_called()


def test_read_clipboard_text_falls_back_when_powershell_empty(monkeypatch) -> None:
    monkeypatch.setattr("kite.ui.attach.os.name", "nt")
    proc = MagicMock(stdout="", returncode=0)
    monkeypatch.setattr("kite.ui.attach.subprocess.run", lambda *a, **k: proc)
    with patch("kite.ui.attach.read_os_clipboard", return_value="fallback"):
        assert read_clipboard_text() == "fallback"
    proc = MagicMock(stdout="ps text", returncode=0)
    monkeypatch.setattr("kite.ui.attach.subprocess.run", lambda *a, **k: proc)
    with patch("kite.ui.attach.read_os_clipboard", return_value="fallback") as low:
        assert read_clipboard_text() == "ps text"
        low.assert_not_called()


def test_wrapped_answer_keeps_the_left_edge() -> None:
    """A streamed line that outruns the row must not wrap back to column 0.

    Streamed cells are written with ``end=""`` to a ``soft_wrap`` console, so
    Rich hands the raw line to the terminal. Without in-harness wrapping every
    continuation row after the first lands at column 0 — the ragged left edge.
    """
    from kite.ui.style import wrap_hanging

    display = RunDisplay(Console(force_terminal=True, width=100, theme=KITE_THEME), state=SessionUiState())
    long_para = (
        "This is a long streamed paragraph that will certainly exceed the console "
        "width so the terminal has to wrap it somewhere, and every continuation "
        "row must keep the same left edge as the first one."
    )

    def rows_for(chunks, width, channel="answer"):
        buf = StringIO()
        console = Console(file=buf, width=width, theme=KITE_THEME, legacy_windows=False, soft_wrap=False)
        display = RunDisplay(console, state=SessionUiState())
        for chunk in chunks:
            display._stream_write(chunk, channel=channel)
        display._end_stream_line()
        return [ln for ln in strip_ansi(buf.getvalue()).splitlines() if ln.strip()]

    def lead(row):
        return len(row) - len(row.lstrip(" "))

    # One chunk and many small chunks must land on the same boundaries.
    single = rows_for([long_para], 60)
    chunked = rows_for([long_para[i:i + 7] for i in range(0, len(long_para), 7)], 60)
    assert len(single) > 1 and len(chunked) > 1
    assert [lead(r) for r in single[1:]] == [2] * (len(single) - 1)
    assert [lead(r) for r in chunked[1:]] == [2] * (len(chunked) - 1)
    def words(rows):
        """Reassembled words, ignoring the leading cell glyph."""
        joined = " ".join(rows).replace("•", " ", 1)
        return joined.split()

    # Wrapping must not lose or duplicate text: reassembling the rows recovers
    # the original paragraph.
    assert words(single) == long_para.split()
    assert words(chunked) == long_para.split()

    # A word is never split across rows when the chunks land inside it. The row
    # near the edge defers its trailing token until the word is complete.
    wordy = " ".join(["verification"] * 10)
    for size in (3, 5, 8, 13):
        rows = rows_for([wordy[i:i + size] for i in range(0, len(wordy), size)], 60)
        joined = " ".join(rows).replace("•", " ", 1)
        assert not re.search(r"[a-z]\n\s+[a-z]", "\n".join(rows)), f"split a word at chunk={size}"
        assert joined.split() == wordy.split(), f"text lost at chunk={size}"

    # An unbreakable token (long URL) must still wrap inside the cell.
    url = "see " + "https://example.com/" + "a" * 90 + " for details"
    url_rows = rows_for([url], 60)
    assert len(url_rows) > 1
    assert all(lead(r) == 2 for r in url_rows[1:])

    # Short lines are untouched.
    assert rows_for(["short one\nshort two"], 60) == ["• short one", "  short two"]

    # An unusable width defers to Rich instead of guessing or crashing.
    narrow = RunDisplay(Console(file=StringIO(), width=8, theme=KITE_THEME), state=SessionUiState())
    assert narrow._wrap_width() == 0
    narrow._stream_write_answer(long_para[:40])
    assert narrow._answer_col > 0

    # Thinking is full-width by design: it wraps, but keeps column 0.
    think = rows_for([long_para[i:i + 20] for i in range(0, len(long_para), 20)], 60, channel="thinking")
    assert len(think) > 1
    assert all(lead(r) == 0 for r in think)

    # A closed list item's continuation clears the bullet, not just the gutter.
    # Markdown cues only apply to whole lines, so the line must be newline-ended.
    bullets = rows_for(["- level one item that runs on and on and should wrap cleanly\n"], 60)
    assert len(bullets) > 1
    assert lead(bullets[1]) == 4

    # An indented heading keeps its own lead instead of jumping left. The `##`
    # markers are dropped and the lead preserved, so a 2-space indent still
    # shows as 2 columns rather than snapping to the gutter.
    assert display._prose_line_style("  ## Heading")[1] == "  Heading"
    assert display._prose_line_style("## Heading")[1] == "Heading"
    assert display._prose_line_style("  - item")[1] == "  • item"
    heading = rows_for(["  ## Heading that is quite long and will need to wrap here\n"], 60)
    assert "Heading" in heading[0] and "##" not in heading[0]
    # lead() counts spaces only; the cell glyph occupies the first 2 columns.
    assert heading[0].index("Heading") == 4

    # The helper itself: fits unchanged, wraps with the continuation indent.
    assert wrap_hanging("short", first_indent="  ", cont_indent="  ", width=40) == "short"
    out = wrap_hanging("aaa bbb ccc", first_indent="  ", cont_indent="    ", width=9)
    assert out == "aaa bbb\n    ccc"
    assert wrap_hanging("a\tb", first_indent="", cont_indent="", width=4) == "a   \nb"

    # Chunk boundaries inside a word must not become extra output rows.
    rows = rows_for(("Kite is a", " terminal coding", "-agent harness.\n", "Second", " line\n"), 100)
    assert rows == ["• Kite is a terminal coding-agent harness.", "  Second line"]


def test_composer_turn_answer_lifecycle() -> None:
    from kite.ui.render import render_user_cell

    console = Console(file=StringIO(), width=48, height=24, theme=KITE_THEME, legacy_windows=False)
    rows = console.render_lines(render_user_cell("ship the fix"), console.options)
    assert len(rows) == 3
    assert all(len("".join(segment.text for segment in row)) == 48 for row in rows)
    assert any(segment.style is not None and segment.style.bgcolor for segment in rows[1])
    assert "ship the fix" in "".join(segment.text for segment in rows[1])
    multi = console.render_lines(render_user_cell("one\ntwo"), console.options)
    assert len(multi) == 4
    assert all(len("".join(segment.text for segment in row)) == 48 for row in multi)
    assert "two" in "".join(segment.text for segment in multi[2])

    events = [
        Event("agent_start", payload={"task": "hi", "provider": "groq", "model": "llama"}),
        Event("agent_end", payload={"exit_status": "Submitted", "submission": "Hello there", "cost": 0.0}),
    ]
    with_composer = StringIO()
    display = RunDisplay(Console(file=with_composer, width=80, theme=KITE_THEME), state=SessionUiState())
    display.state.busy = True
    display.composer_owns_input = True
    for event in events:
        display(event)
    assert "Hello there" not in strip_ansi(with_composer.getvalue())

    # No stream_delta arrived, so teardown still commits the canonical answer.
    display.finish_composer_turn(events[-1].payload)
    plain = strip_ansi(with_composer.getvalue())
    assert "hi" not in plain
    assert plain.count("Hello there") == 1
    assert "work complete" not in plain
    assert "kite · " not in plain

    without_composer = StringIO()
    headless = RunDisplay(Console(file=without_composer, width=80, theme=KITE_THEME), state=SessionUiState())
    headless.state.busy = True
    for event in events:
        headless(event)
    plain_headless = strip_ansi(without_composer.getvalue())
    assert "hi" in plain_headless
    assert "kite · " in plain_headless

    missing = StringIO()
    absent = RunDisplay(Console(file=missing, width=80, theme=KITE_THEME), state=SessionUiState())
    absent.composer_owns_input = True
    absent(Event("agent_start", payload={"task": "hi"}))
    absent(Event("stream_delta", payload={"text": "Hello "}))
    absent(Event("stream_delta", payload={"text": "there"}))
    absent(Event("agent_end", payload={"exit_status": "Submitted"}))
    # Live streaming: the text is already on screen before teardown.
    assert strip_ansi(missing.getvalue()).count("Hello there") == 1
    absent.finish_composer_turn()
    # Teardown must not paint it a second time.
    assert strip_ansi(missing.getvalue()).count("Hello there") == 1

    preview_buf = StringIO()
    preview_display = RunDisplay(Console(file=preview_buf, width=120, theme=KITE_THEME), state=SessionUiState())
    for partial_args in ('{"message":"first', '{"message":"first answer"}'):
        preview_display(
            Event(
                "stream_tool",
                payload={"name": "submit", "partial_args": partial_args, "phase": "args"},
            )
        )
    assert "preparing" not in strip_ansi(preview_buf.getvalue())
    preview_display(Event("stream_end", payload={}))
    assert strip_ansi(preview_buf.getvalue()).count("preparing") == 1

    single = StringIO()
    once = RunDisplay(Console(file=single, width=80, theme=KITE_THEME), state=SessionUiState())
    for event in (
        Event("agent_start", payload={"task": "hi"}),
        Event("stream_delta", payload={"text": "Hello there"}),
        Event("tool_start", payload={"tool": "submit", "arguments": {}}),
        Event("agent_end", payload={"exit_status": "Submitted", "submission": "Hello there"}),
    ):
        once(event)
    assert strip_ansi(single.getvalue()).count("Hello there") == 1

    # Issue #81: informational answer must survive a no-change Done/Changed/Verification submit.
    issue = StringIO()
    keep = RunDisplay(Console(file=issue, width=80, theme=KITE_THEME), state=SessionUiState())
    keep.composer_owns_input = True
    keep(Event("agent_start", payload={"task": "tell main features of kite"}))
    keep(Event("stream_delta", payload={"text": "Kite features: fast runs"}))
    keep(Event("agent_end", payload={"exit_status": "Submitted", "submission": "## Done\n- Shared an overview"}))
    keep.finish_composer_turn()
    kept = strip_ansi(issue.getvalue())
    assert "Kite features: fast runs" in kept
    assert "Shared an overview" not in kept

    buf2 = StringIO()
    busy = RunDisplay(Console(file=buf2, width=80, theme=KITE_THEME), state=SessionUiState())
    busy.composer_owns_input = True
    busy(Event("agent_start", payload={"task": "fix tests"}))
    busy(Event("stream_delta", payload={"text": "Root cause was a race in auth"}))
    busy(
        Event(
            "agent_end",
            payload={
                "exit_status": "Submitted",
                "submission": "## Done\n- Fixed the flake",
                "verification": {"artifact_count": 1, "diff_count": 1},
            },
        )
    )
    busy.finish_composer_turn()
    plain2 = strip_ansi(buf2.getvalue())
    assert "Root cause was a race in auth" in plain2 and "Done" in plain2 and "Fixed the flake" in plain2


def test_repl_prints_each_submitted_prompt_once(monkeypatch, tmp_path, kite_home) -> None:
    from kite.ui.complete import ComposerResult

    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: MagicMock(provider="groq", model="llama-test"),
    )
    monkeypatch.setattr(ChatSession, "_schedule_release_check_legacy", lambda self: None)
    monkeypatch.setattr(ChatSession, "_prewarm_composer", lambda self: None)

    session = ChatSession(cwd=str(tmp_path))
    rows: list[str] = []
    session.display.print_user_turn = rows.append  # type: ignore[method-assign]
    session._run_task = lambda task, **kwargs: None  # type: ignore[method-assign]
    prompts = [
        ComposerResult("text", "first"),
        ComposerResult("text", "second"),
        ComposerResult("eof"),
    ]
    session._read_input = lambda: prompts.pop(0)  # type: ignore[method-assign]

    assert session.run() == 0
    assert rows == ["first", "second"]


def test_resume_transcript_rendering_and_tail(tmp_path, kite_home) -> None:
    from kite.memory.session import Session, SessionMeta

    session = ChatSession(cwd=str(tmp_path))
    buf = StringIO()
    session.console = Console(file=buf, force_terminal=False)
    meta = SessionMeta(
        id="abc12345",
        created_at=1.0,
        updated_at=2.0,
        cwd=str(tmp_path),
        provider="p",
        model="m",
        task="demo",
    )
    loaded = Session(
        meta=meta,
        messages=[{"role": "user", "content": f"msg-{i}"} for i in range(15)],
    )
    session._print_session(loaded, tail=None)
    out = buf.getvalue()
    assert "earlier messages" not in out
    assert "msg-0" in out
    assert "msg-14" in out

    # Issue #83: resume renders all kinds chronologically with full bodies (no silent truncation).
    chat = ChatSession(cwd=str(tmp_path))
    buf2 = StringIO()
    chat.console = Console(file=buf2, force_terminal=False, width=400)
    long_answer = "line-one\nline-two\n" + "y" * 300
    meta83 = SessionMeta(
        id="sess83", created_at=1.0, updated_at=2.0, cwd=str(tmp_path), provider="p", model="m", task="demo",
    )
    loaded83 = Session(
        meta=meta83,
        messages=[
            {"role": "user", "content": "What is Kite? Reply in three concise bullets."},
            {
                "role": "assistant",
                "content": "Kite is a coding agent.",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "read", "arguments": '{"path": "a"}'}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "file body here"},
            {"role": "assistant", "content": long_answer},
            {
                "role": "exit",
                "content": "Submitted",
                "extra": {"exit_status": "Submitted", "submission": "final output bullets"},
            },
        ],
    )
    chat._print_session(loaded83, tail=None)
    out83 = strip_ansi(buf2.getvalue())
    bits = ["What is Kite?", "Kite is a coding agent.", "read", "file body here", "line-one", "final output bullets"]
    positions = [out83.index(bit) for bit in bits]
    assert positions == sorted(positions)
    assert "y" * 300 in out83
    assert "line-two" in out83
    assert "…" not in out83

    assert session._parse_session_show_tail("abc --tail 5") == ("abc", 5)
    assert session._parse_session_show_tail("abc --tail 0") == ("abc", None)
    assert session._parse_session_show_tail("abc") == ("abc", 20)
    assert session._parse_session_show_tail("--tail 3 abc") == ("abc", 3)


def test_reasoning_picker_and_slash_levels(tmp_path, kite_home, reasoning_support) -> None:
    from kite.models.reasoning import ReasoningSupport

    session = ChatSession(cwd=str(tmp_path))
    session._reasoning_support = reasoning_support
    keys = [key for key, _ in session._reasoning_picker_choices()]
    assert "auto" in keys

    nodisable = ChatSession(cwd=str(tmp_path))
    nodisable._reasoning_support = ReasoningSupport(
        supported=True,
        can_fast=True,
        can_thinking=True,
        can_disable=False,
    )
    assert "off" not in [key for key, _ in nodisable._reasoning_picker_choices()]
    assert "auto" in [key for key, _ in nodisable._reasoning_picker_choices()]

    buf = StringIO()
    think = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    think.console = Console(file=buf, force_terminal=False)
    think._reasoning_support = reasoning_support
    think._harness = MagicMock()
    think._harness_key = ("groq", "llama-3.3-70b", "build", "auto", False, None, None, "auto", True, "", "", None, None, None, False, False, False, "auto", False)

    think._slash_thinking("high")
    assert think.state.reasoning == "thinking:high"
    assert think._harness is None
    assert "thinking" in strip_ansi(buf.getvalue()).lower()

    think._slash_thinking("")
    assert think.state.reasoning == "off"

    think._slash_fast("")
    assert think.state.reasoning == "fast:low"

    legacy = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    legacy.console = Console(file=StringIO(), force_terminal=False)
    legacy._reasoning_support = reasoning_support
    legacy._slash_reasoning("fast")
    assert legacy.state.reasoning == "fast:low"
    legacy._slash_reasoning("auto")
    assert legacy.state.reasoning == "auto"

    dispatched = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    dispatched.console = Console(file=StringIO(), force_terminal=False)
    dispatched._reasoning_support = reasoning_support
    assert dispatched._handle_slash("/thinking medium") is True
    assert dispatched.state.reasoning == "thinking:medium"
    assert dispatched._handle_slash("/fast") is True
    assert dispatched.state.reasoning == "fast:low"
    assert dispatched._handle_slash("/reasoning thinking:high") is True
    assert dispatched.state.reasoning == "thinking:high"


def test_variants_strict_menu_persist_and_label(tmp_path, kite_home, reasoning_support) -> None:
    from kite.ui.status import format_model_label

    session = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    session.console = Console(file=StringIO(), force_terminal=False, width=120)
    session._reasoning_support = reasoning_support
    session._harness = MagicMock()

    session._slash_variants("high")
    assert session.state.reasoning == "thinking:high"
    assert UserConfig.load().reasoning == "thinking:high"
    assert format_model_label(session.state) == "groq/llama-3.3-70b#high"

    before = session.state.reasoning
    session._slash_variants("max")  # not offered: strict reject, no clamp
    assert session.state.reasoning == before
    assert "max is not offered" in strip_ansi(session.console.file.getvalue())

    session._slash_variants("off")
    assert session.state.reasoning == "off"
    assert format_model_label(session.state) == "groq/llama-3.3-70b#off"

    assert session._handle_slash("/variants low") is True
    assert session.state.reasoning == "fast:low"

    # Fresh sessions inherit the saved default; auto stays bare.
    fresh = ChatSession(cwd=str(tmp_path))
    assert fresh.state.reasoning == "fast:low"
    assert format_model_label(SessionUiState(model="m", provider="p")) == "p/m"


def test_variants_unknown_support_strict_reject_and_known_absent(tmp_path, kite_home, reasoning_support) -> None:
    """Unknown detection applies nothing; known-absent keeps its message."""
    from kite.models.reasoning import ReasoningSupport

    session = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    session.console = Console(file=StringIO(), force_terminal=False, width=120)
    session._model_resolved = True
    before = session.state.reasoning

    # Unknown: bounded detection fails → strict reject, state untouched.
    session._reasoning_info_sync = lambda **_k: None
    session._slash_variants("high")
    assert session.state.reasoning == before
    assert "could not confirm" in strip_ansi(session.console.file.getvalue())

    # Known-absent: the current message is preserved.
    session._reasoning_info_sync = lambda **_k: ReasoningSupport(False, False, False, False, source="live")
    session._slash_variants("high")
    assert session.state.reasoning == before
    assert "does not advertise" in strip_ansi(session.console.file.getvalue())

    session = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    session.console = Console(file=StringIO(), force_terminal=False, width=120)
    session._model_resolved = True
    session._harness = MagicMock()
    calls = {"n": 0}

    def _flaky(**_k):
        calls["n"] += 1
        return None if calls["n"] == 1 else reasoning_support

    session._reasoning_info_sync = _flaky
    session._slash_variants("high")  # re-detect proves support → applies
    assert session.state.reasoning == "thinking:high"


def test_reasoning_info_sync_bounded_never_hangs(tmp_path, kite_home, monkeypatch) -> None:
    """Unknown support returns after a bounded join without caching a result."""
    from kite.models import reasoning
    from kite.ui import repl

    session = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    session.console = Console(file=StringIO(), force_terminal=False, width=120)
    session._model_resolved = True
    joins = []

    class StalledThread:
        def __init__(self, *, target, daemon, name):
            assert daemon
            self.started = False

        def start(self):
            self.started = True

        def join(self, timeout):
            assert self.started
            joins.append(timeout)

        def is_alive(self):
            return True

    monkeypatch.setattr(reasoning, "peek_reasoning", lambda *_a, **_k: None)
    monkeypatch.setattr(repl.threading, "Thread", StalledThread)
    assert session._reasoning_info_sync(timeout=0.5, announce=False) is None
    assert joins == [0.5]
    assert session._reasoning_support is None


def test_pending_approval_panel_plan_git_footer(tmp_path, kite_home) -> None:
    """Busy-tick crash: panel id must exist before the first approval render (no AttributeError)."""
    from kite.application.policy import ApprovalRequest
    from kite.ui.approval import render_approval_panel

    diff = make_unified_diff("app.py", "old\n", "new\n")
    panel = render_approval_panel("edit", {"path": "app.py"}, diff=diff).plain
    assert "approve" in panel.lower()
    assert "app.py" in panel
    assert "+1" in panel and "-1" in panel

    chat = ChatSession(cwd=str(tmp_path))
    buf = StringIO()
    chat.console = Console(file=buf, force_terminal=False, width=120)
    req = ApprovalRequest(
        request_id="req-first-tick",
        tool="bash",
        arguments={"command": "rm -rf /tmp/kite-proof"},
        reason="destructive",
        mandatory=True,
    )
    chat._approval_coordinator._pending = req
    chat._show_pending_approval_panel()
    out = strip_ansi(buf.getvalue())
    assert "bash" in out
    assert chat._approval_panel_id == "req-first-tick"
    before = buf.getvalue()
    chat._show_pending_approval_panel()
    assert buf.getvalue() == before

    # Read-only runs must not attach git checkpoints (no commit lines, no git writes).
    from types import SimpleNamespace

    ro = ChatSession(cwd=str(tmp_path))
    harness = SimpleNamespace(checkpoints="sentinel")
    ro.state.mode = AgentMode.PLAN
    ro._wire_harness_git(harness)
    assert harness.checkpoints is None
    ro.state.mode = AgentMode.BUILD
    ro._wire_harness_git(harness)
    assert harness.checkpoints is ro.git

    # Failed turns leave a durable footer notice; the next turn clears it.
    from kite.ui.status import format_status_tail

    ro2 = ChatSession(cwd=str(tmp_path))
    assert all(not text.startswith("err ") for text, _ in status_segments(ro2.state))
    ro2.state.last_error = "step or cost budget reached " + "x" * 100
    texts = dict(status_segments(ro2.state))
    err = next(text for text in texts if text.startswith("err "))
    assert err.endswith("…") and len(err) <= len("err ") + 64
    assert texts[err] == "kite.error"
    assert "err " in format_status_tail(ro2.state)
    ro2._begin_turn_state("do things")
    assert ro2.state.last_error == "" and ro2.state.last_trace == ""
    assert ro2.state.running_label == "do things"


def test_git_dirty_tracking_and_branch_marker(tmp_path, kite_home, monkeypatch) -> None:
    """Concrete git state: live dirty count, turn-end announce, branch * marker."""
    import shutil
    import subprocess
    from io import StringIO

    from rich.console import Console

    from kite.ui.git import git_dirty_count
    from kite.ui.status import status_context_parts

    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    # Hermetic: ceiling the parent so no repo above tmp_path leaks in
    # (this machine nests Temp inside a home-directory repo).
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert git_dirty_count(str(tmp_path)) == -1
    # Own subdirectory: debris left in a reused basetemp would otherwise show up
    # as an extra untracked file and make the dirty count flaky.
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=60)
    from kite.ui import git as git_ui

    git_ui._status_cache.clear()
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t"],
        check=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "t"],
        check=True,
        timeout=60,
    )
    assert git_dirty_count(str(repo)) == 0
    (repo / "new.txt").write_text("x", encoding="utf-8")
    git_ui._status_cache.clear()
    assert git_dirty_count(str(repo)) == 1

    chat = ChatSession(cwd=str(repo))
    buf = StringIO()
    chat.console = Console(file=buf, force_terminal=False)
    git_ui._status_cache.clear()
    chat._refresh_git_state(announce=True)
    assert chat.state.git_dirty == 1
    assert "1 uncommitted file" in buf.getvalue()

    chat.state.git_branch = "main"
    assert "main*" in status_context_parts(chat.state)
    chat.state.git_dirty = 0
    assert "main" in status_context_parts(chat.state)
    assert "main*" not in status_context_parts(chat.state)


def test_git_helpers_survive_missing_binary_and_cache_repo(tmp_path, monkeypatch) -> None:
    from kite.ui import git as git_ui

    calls: list[int] = []

    def _boom(*args, **kwargs):  # noqa: ANN001, ANN202
        calls.append(1)
        raise FileNotFoundError("no git")

    monkeypatch.setattr(git_ui.subprocess, "run", _boom)
    git_ui._repo_cache.clear()
    assert git_ui.is_repo(tmp_path) is False
    assert git_ui.git_dirty_count(tmp_path) == -1
    assert git_ui.git_branch(tmp_path) == ""
    assert git_ui.GitCheckpoints.open(tmp_path).undo() == (False, "not a git repo — nothing to undo")
    calls.clear()
    git_ui._repo_cache.clear()
    assert git_ui.is_repo(tmp_path) is False
    assert git_ui.is_repo(tmp_path) is False
    assert len(calls) == 1


def test_raw_multiselect_retains_checks_hidden_by_filter(monkeypatch) -> None:
    from kite.ui import pick

    events = iter(("space", "b", "space", "enter"))
    monkeypatch.setattr(pick, "_event_reader", lambda drawn: lambda: next(events))
    monkeypatch.setattr(pick, "_ensure_vt_output", lambda: None)
    monkeypatch.setattr(pick, "_screen_height", lambda: 30)
    monkeypatch.setattr(pick.sys, "stderr", StringIO())
    console = Console(file=StringIO(), width=80, height=30, theme=KITE_THEME)
    result = pick._raw_pick(
        console, [("a", "alpha"), ("b", "beta")], current=None,
        title="Models", noun="model", show=10, refreshable=False, multiple=True,
    )
    assert result == ["a", "b"]


def test_ui_package_does_not_eagerly_import_renderers() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import sys; import kite.ui; print('kite.ui.render' in sys.modules, 'rich.console' in sys.modules, 'prompt_toolkit' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "False False False"
