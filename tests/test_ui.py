"""REPL, render, theme, composer, attach, preview, privacy."""

from __future__ import annotations

import inspect
from contextlib import nullcontext
from dataclasses import dataclass
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
    user_content_with_attachments,
)
from kite.ui.complete import read_repl_line
from kite.ui.diff import count_diff_lines, make_unified_diff, preview_mutating_diff, preview_patch_diff, render_diff
from kite.ui.empty import render_empty
from kite.ui.render import RunDisplay
from kite.ui.repl import ChatSession
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.status import format_status_tail, render_status, status_segments
from kite.ui.streaming import StreamCoalescer
from kite.ui.style import KITE_THEME
from kite.ui.theme import (
    THEME_NAMES,
    brand_fg,
    palette,
    pt_style_dict,
    reset_prefs,
    resolved_theme,
    set_theme,
)
from kite.ui.tool_cards import render_code_edit_preview
from tests.conftest import strip_ansi


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
    reset_prefs(theme="auto", font="unicode")
    for name in ("monochrome", "catppuccin", "ember", "forest", "hues", "transparent"):
        assert name in THEME_NAMES
        assert "kite.brand" in palette(name)["styles"]
    assert set_theme("glass") == "transparent"
    assert "bg:default" in pt_style_dict("transparent")["bottom-toolbar"]
    dark_styles = pt_style_dict("kite")
    assert dark_styles["composer"] == "bg:#30303c"
    assert dark_styles["prompt"].startswith("bg:#30303c ")
    assert dark_styles["completion-menu.completion.current"] == "bg:default #a8ffff bold"
    assert pt_style_dict("transparent")["composer"] == "bg:default"
    for name in THEME_NAMES:
        ui = palette(name)["ui"]
        assert ui.completion_current_bg == ui.completion_bg
    assert set_theme("catpuccin") == "catppuccin" and resolved_theme("catpuccin") == "catppuccin"
    brands = {name: brand_fg(name) for name in ("kite", "catppuccin", "ember", "forest", "hues")}
    assert len(set(brands.values())) == len(brands)
    state = SessionUiState(mode=AgentMode.PLAN, approval=ApprovalMode.READONLY, model="llama", provider="groq", todos=[TodoItem(id="1", content="ship", status="in_progress")])
    tail = format_status_tail(state)
    rendered = render_status(state).plain
    for text, _style in status_segments(state):
        assert text in tail and text in rendered
    assert "/kill all" in render_empty("no jobs", hint="/kill all").plain
    reset_prefs(theme="auto", font="unicode")


def test_composer_interrupt_kinds_aliases_and_empty() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("prompt_toolkit.patch_stdout.patch_stdout", lambda raw=False: nullcontext())
    try:
        session = MagicMock()
        session.prompt.side_effect = KeyboardInterrupt()
        session.default_buffer.text = ""
        assert read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None).kind == "empty"
        session.prompt.side_effect = KeyboardInterrupt()
        session.default_buffer.text = "use grep not find"
        steered = read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None, busy=True)
        assert steered.kind == "steer" and steered.text == "use grep not find"
        session.prompt.side_effect = KeyboardInterrupt()
        session.default_buffer.text = ""
        assert read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None, busy=True).kind == "stop"
        session.prompt.side_effect = EOFError()
        assert read_repl_line(session=session, state=SessionUiState(), fallback=lambda: None).kind == "eof"
    finally:
        monkeypatch.undo()
    q = RunMessageQueue()
    q.enqueue("later")
    q.steer("now")
    assert q.counts() == (1, 1) and q.drain_all() == [("now", True), ("later", False)]
    assert set_persistence_mode("disabled") == "disabled"
    assert UserConfig.load().session_persistence == "disabled"
    set_persistence_mode("redacted")
    summary = persistence_summary()
    assert "ssrf" in summary and summary["session_persistence"] in {"full", "redacted", "disabled"}

    from kite.cli.slash import CommandIndex, resolve_slash
    from kite.ui.complete import classify_busy_line

    parsed = resolve_slash("/exit", CommandIndex.load("."))
    assert parsed.command == "quit"
    assert classify_busy_line("/exit").kind == "eof"

    got = read_repl_line(session=None, state=SessionUiState(), fallback=lambda: "   ")
    assert got.kind == "empty"


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
    applied: list[tuple[str, str]] = []
    session._apply_connected = lambda p, m: applied.append((p, m))  # type: ignore[method-assign]
    assert session._handle_slash("/models ollama llama3.2") is True
    assert applied == [("ollama", "llama3.2")]
    handlers = session._slash_handlers()
    for name in ("compact", "keys", "clip"):
        params = [p for p in inspect.signature(handlers[name]).parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        assert params

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
            self.kill_all_calls = 0
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
            self.kill_all_calls += 1
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
    session._teardown_jobs()
    assert session.jobs.kill_all_calls >= 1  # type: ignore[attr-defined]
    calls: list[dict] = []
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **kwargs: calls.append(kwargs) or (_ for _ in ()).throw(AssertionError("no resolve")))
    ChatSession(cwd=str(tmp_path))
    assert not calls
    resolved = MagicMock(provider="groq", model="llama-test")
    monkeypatch.setattr("kite.providers.resolve.resolve_model", lambda **_: resolved)
    live = ChatSession(cwd=str(tmp_path))
    live._ensure_model_resolved()
    assert live._make_harness() is live._make_harness()
    seen: dict = {}
    monkeypatch.setattr("kite.agent.harness_build.build_harness_config", lambda **kwargs: seen.update(kwargs) or MagicMock())
    monkeypatch.setattr("kite.agent.harness.Harness", lambda config: MagicMock(config=config, last_session=None))
    flagged = ChatSession(cwd=str(tmp_path), step_limit=4, role="debugger", long_task=True)
    flagged._ensure_model_resolved()
    flagged._make_harness()
    assert seen["step_limit"] == 4 and seen["role"] == "debugger"
    repl = ChatSession(cwd=".", provider="fake", model="fake")
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
    diff = preview_patch_diff("src/foo.py", "old line\n", "new line\n")
    assert "-old line" in diff and "+new line" in diff
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


def test_stream_answer_styles_boundaries_and_coalescing() -> None:
    display = RunDisplay(Console(force_terminal=True, width=100, theme=KITE_THEME), state=SessionUiState())
    display._stream_write_answer("## Summary\n- first item\n```python\nx = 1\n```\n")
    # fence markers and bullet land in internal stream path — exercise prose helper directly
    style, body = display._prose_line_style("- item")
    assert body.startswith("• ") and style == "kite.answer"
    style, body = display._prose_line_style("## Title")
    assert body == "Title" and "bold" in style

    coalescer = StreamCoalescer(min_chars=4, flush_chars=100, max_latency_s=0.0)
    assert coalescer.push("custom", "hi") is None
    assert coalescer.push("custom", " there") is not None

    buf = StringIO()
    inline = RunDisplay(Console(file=buf, width=100, theme=KITE_THEME), state=SessionUiState())
    for chunk in ("Kite is a", " terminal coding", "-agent harness.\n", "Second", " line\n"):
        inline._stream_write_answer(chunk)
    lines = [line for line in strip_ansi(buf.getvalue()).splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0].strip() == "• Kite is a terminal coding-agent harness."
    assert lines[1].strip() == "Second line"


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
    assert "Hello there" not in strip_ansi(missing.getvalue())
    absent.finish_composer_turn()
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


def test_approval_panels_render_once() -> None:
    from kite.ui.approval import render_approval_panel

    diff = make_unified_diff("app.py", "old\n", "new\n")
    panel = render_approval_panel("edit", {"path": "app.py"}, diff=diff).plain
    assert "approve" in panel.lower()
    assert "app.py" in panel
    assert "+1" in panel and "-1" in panel


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


def test_reasoning_picker_and_slash_levels(tmp_path, kite_home) -> None:
    from kite.models.reasoning import ReasoningSupport

    def _support() -> ReasoningSupport:
        return ReasoningSupport(
            supported=True,
            can_fast=True,
            can_thinking=True,
            can_disable=True,
            thinking_kwargs={"reasoning_effort": "high"},
            fast_kwargs={"reasoning_effort": "low"},
            efforts=("none", "low", "medium", "high"),
        )

    session = ChatSession(cwd=str(tmp_path))
    session._reasoning_support = _support()
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
    think._reasoning_support = _support()
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
    legacy._reasoning_support = _support()
    legacy._slash_reasoning("fast")
    assert legacy.state.reasoning == "fast:low"
    legacy._slash_reasoning("auto")
    assert legacy.state.reasoning == "auto"

    dispatched = ChatSession(cwd=str(tmp_path), provider="groq", model="llama-3.3-70b")
    dispatched.console = Console(file=StringIO(), force_terminal=False)
    dispatched._reasoning_support = _support()
    assert dispatched._handle_slash("/thinking medium") is True
    assert dispatched.state.reasoning == "thinking:medium"
    assert dispatched._handle_slash("/fast") is True
    assert dispatched.state.reasoning == "fast:low"
    assert dispatched._handle_slash("/reasoning thinking:high") is True
    assert dispatched.state.reasoning == "thinking:high"


def test_pending_approval_panel_plan_git_footer(tmp_path, kite_home) -> None:
    """Busy-tick crash: panel id must exist before the first approval render (no AttributeError)."""
    from kite.application.policy import ApprovalRequest

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
    from kite.ui.status import format_status_tail, status_segments

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
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    from kite.ui import git as git_ui

    git_ui._status_cache.clear()
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"],
        check=True,
        timeout=60,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "t"],
        check=True,
        timeout=60,
    )
    assert git_dirty_count(str(tmp_path)) == 0
    (tmp_path / "new.txt").write_text("x", encoding="utf-8")
    git_ui._status_cache.clear()
    assert git_dirty_count(str(tmp_path)) == 1

    chat = ChatSession(cwd=str(tmp_path))
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
