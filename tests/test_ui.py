"""REPL, render, theme, composer, attach, preview, privacy."""

from __future__ import annotations

import inspect
from contextlib import nullcontext
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from kite.ui.stream_buffer import StreamCoalescer
from kite.ui.tool_cards import render_code_edit_preview
from kite.ui.empty import render_empty
from kite.ui.render import RunDisplay
from kite.ui.repl import ChatSession
from kite.ui.state import SessionUiState, TodoItem
from kite.ui.status import format_status_tail, render_status, status_segments
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
from tests.conftest import strip_ansi


def test_render_events_and_busy_spin() -> None:
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
    display(Event("agent_end", payload={"exit_status": "LimitsExceeded", "content": "step budget 40/40", "limit_kind": "steps", "steps": 40, "step_limit": 40}))
    assert "continue" in buf.getvalue().lower()
    display.state.busy = True
    display._spin(True, "thinking")
    assert display._spinner_on is False and display.state.running_label == "thinking"


def test_theme_palettes_and_status() -> None:
    reset_prefs(theme="auto", font="unicode")
    for name in ("monochrome", "catppuccin", "ember", "forest", "hues", "transparent"):
        assert name in THEME_NAMES
        assert "kite.brand" in palette(name)["styles"]
    assert set_theme("glass") == "transparent"
    assert "bg:default" in pt_style_dict("transparent")["bottom-toolbar"]
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


def test_composer_ctrl_c_queue_and_privacy(monkeypatch, kite_home) -> None:
    monkeypatch.setattr("prompt_toolkit.patch_stdout.patch_stdout", lambda raw=False: nullcontext())
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
    q = RunMessageQueue()
    q.enqueue("later")
    q.steer("now")
    assert q.counts() == (1, 1) and q.drain_all() == [("now", True), ("later", False)]
    assert set_persistence_mode("disabled") == "disabled"
    assert UserConfig.load().session_persistence == "disabled"
    set_persistence_mode("redacted")
    summary = persistence_summary()
    assert "ssrf" in summary and summary["session_persistence"] in {"full", "redacted", "disabled"}


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


def test_attach_preview_and_clipboard(tmp_path, kite_home, monkeypatch) -> None:
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


def test_render_diff_and_stream_answer_styles() -> None:
    diff = make_unified_diff("src/a.py", "line one\n", "line two\n")
    rendered = render_diff(diff, collapsed=True).plain
    assert "src/a.py" in rendered
    assert "+1" in rendered and "-1" in rendered
    assert "line two" in rendered and "line one" in rendered

    preview = render_code_edit_preview(
        "edit",
        {"path": "lib/x.py", "old": "foo", "new": "bar"},
    )
    assert preview is not None
    assert "lib/x.py" in preview.plain
    assert "foo" in preview.plain and "bar" in preview.plain

    display = RunDisplay(Console(force_terminal=True, width=100, theme=KITE_THEME), state=SessionUiState())
    display._stream_write_answer("## Summary\n- first item\n```python\nx = 1\n```\n")
    # fence markers and bullet land in internal stream path — exercise prose helper directly
    style, body = display._prose_line_style("- item")
    assert body.startswith("• ") and style == "kite.answer"
    style, body = display._prose_line_style("## Title")
    assert body == "Title" and "bold" in style

    coalescer = StreamCoalescer(min_chars=4, flush_chars=100, max_latency_s=0.0)
    assert coalescer.push("answer", "hi") is None
    assert coalescer.push("answer", " there") is not None


def test_approval_panel_includes_diff_stat() -> None:
    from kite.ui.approval import render_approval_panel

    diff = make_unified_diff("app.py", "old\n", "new\n")
    panel = render_approval_panel("edit", {"path": "app.py"}, diff=diff).plain
    assert "approve" in panel.lower()
    assert "app.py" in panel
    assert "+1" in panel and "-1" in panel


def test_empty_repl_enter_does_not_run(tmp_path, kite_home) -> None:
    from io import StringIO

    from kite.ui.complete import read_repl_line

    got = read_repl_line(session=None, state=SessionUiState(), fallback=lambda: "   ")
    assert got.kind == "empty"
    buf = StringIO()
    session = ChatSession(cwd=str(tmp_path), provider="groq", model="llama")
    session.console = Console(file=buf, force_terminal=False)
    session._make_harness = lambda **_k: (_ for _ in ()).throw(AssertionError("blank enter must not start a turn"))  # type: ignore[method-assign]
    session._run_task("  ")
    assert "empty" in buf.getvalue().lower()
