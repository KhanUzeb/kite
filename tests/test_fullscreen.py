"""Fullscreen workbench — fluid stream projection."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.events import Event
from kite.ui.fullscreen import FullscreenReducer, can_show_fullscreen, render_fullscreen
from kite.ui.fullscreen.mode import fullscreen_layout_tier
from kite.ui.fullscreen.render import build_fullscreen_layout, render_stream
from kite.ui.style import KITE_THEME
from tests.conftest import strip_ansi


def test_fullscreen_size_gates() -> None:
    assert fullscreen_layout_tier(80, 24) == "none"
    assert not can_show_fullscreen(80, 24)
    assert can_show_fullscreen(100, 30)
    assert fullscreen_layout_tier(120, 40) == "full"


def test_reducer_fluid_stream_not_semantic_kinds() -> None:
    reducer = FullscreenReducer()
    reducer.apply_event(Event("agent_start", {"task": "fix auth timeout"}))
    reducer.apply_event(Event("tool_start", {"tool": "read", "arguments": {"path": "src/auth.py"}}))
    reducer.apply_event(Event("tool_end", {"tool": "read", "ok": True}))
    stream = reducer.model.stream
    assert stream
    labels = {line.label for line in stream}
    assert "read" in labels
    assert "goal" not in labels
    assert "plan" not in labels


def test_reducer_tracks_changes_and_verification() -> None:
    reducer = FullscreenReducer()
    reducer.apply_event(Event("diff", {"path": "src/auth.py", "added": 4, "deleted": 1}))
    reducer.apply_event(
        Event("verification_record", {"name": "pytest", "ok": True, "output_summary": "18 passed"})
    )
    assert len(reducer.model.review.files) == 1
    assert reducer.model.verification_checks[0].name == "pytest"


def test_render_fullscreen_layout() -> None:
    model = FullscreenReducer().model
    model.repo = "kite"
    model.branch = "main"
    model.stream = []  # type: ignore[method-assign]
    layout = build_fullscreen_layout(model, cols=120, rows=40)
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=True, theme=KITE_THEME)
    console.print(layout)
    plain = strip_ansi(buf.getvalue())
    assert "Stream" in plain and "Work" in plain and "Inspect" in plain


def test_render_stream_shows_tool_lines() -> None:
    reducer = FullscreenReducer()
    reducer.apply_event(Event("tool_start", {"tool": "bash", "arguments": {"command": "pytest -q"}}))
    text = render_stream(reducer.model)
    assert "bash" in text.plain


def test_render_fullscreen_approval_card() -> None:
    reducer = FullscreenReducer()
    reducer.model.approval.active = True
    reducer.model.approval.tool = "bash"
    reducer.model.approval.summary = "run migrations"
    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=True, theme=KITE_THEME)
    body = render_fullscreen(console, reducer.model, cols=100, rows=30)
    console.print(body)
    plain = strip_ansi(buf.getvalue())
    assert "Approval" in plain and "bash" in plain
