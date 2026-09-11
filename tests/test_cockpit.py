"""Run-centric cockpit view model and layout."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.agent.events import Event
from kite.ui.style import KITE_THEME
from kite.application.events import EventSequencer, envelope_from_legacy
from kite.application.ui import RunViewReducer
from kite.ui.cockpit import RunCockpitReducer, can_show_cockpit, preferred_display_mode, render_cockpit_text
from kite.ui.cockpit.mode import cockpit_layout_tier
from kite.ui.cockpit.reducer import RunCockpitReducer as Reducer
from kite.ui.cockpit.review import render_changes_panel, render_verification_panel
from kite.ui.cockpit.view_model import ChangeFile, ReviewState, VerificationCheck
from kite.ui.tool_cards import format_duration_ms, render_tool_card_done
from tests.conftest import strip_ansi


def test_cockpit_mode_gates() -> None:
    assert cockpit_layout_tier(79, 30) == "none"
    assert cockpit_layout_tier(100, 30) == "reduced"
    assert cockpit_layout_tier(120, 40) == "full"
    assert not can_show_cockpit(80, 24)
    assert preferred_display_mode(preference="cockpit", cols=80, rows=24) == "compact"
    assert preferred_display_mode(preference="cockpit", cols=120, rows=40) == "cockpit"


def test_run_cockpit_reducer_timeline_and_changes() -> None:
    reducer = Reducer(run_id="run-1")
    reducer.apply_event(Event("agent_start", {"task": "fix auth timeout"}))
    reducer.apply_event(Event("todo", {"content": "read tests", "status": "in_progress"}))
    reducer.apply_event(Event("tool_start", {"tool": "read", "path": "src/auth.py"}))
    reducer.apply_event(Event("tool_end", {"tool": "read", "ok": True, "path": "src/auth.py"}))
    reducer.apply_event(
        Event(
            "tool_end",
            {"tool": "edit", "ok": True, "path": "src/auth.py", "diff": "--- a/src/auth.py\n+++ b/src/auth.py\n@@\n-old\n+new\n"},
        )
    )
    reducer.apply_event(Event("verification_status", {"status": "verified"}))
    model = reducer.model
    assert model.goal == "fix auth timeout"
    assert model.review.verified
    assert any(e.kind == "goal" for e in model.timeline)
    assert any(e.kind == "tool" for e in model.timeline)
    assert model.review.files and model.review.files[0].path == "src/auth.py"
    snap = model.snapshot()
    assert snap["timeline_count"] >= 3 and snap["verified"] is True


def test_run_cockpit_approval_and_verification() -> None:
    reducer = Reducer()
    reducer.apply_event(Event("approval", {"phase": "request", "tool": "bash", "summary": "run migrations", "mandatory": True}))
    assert reducer.model.approval.active and reducer.model.approval.mandatory
    reducer.apply_event(Event("approval", {"phase": "decision", "decision": "allow"}))
    assert not reducer.model.approval.active
    reducer.apply_event(Event("submit_blocked", {"reason": "tests not run"}))
    assert reducer.model.status == "blocked"
    assert "tests not run" in reducer.model.errors


def test_run_view_reducer_envelope() -> None:
    seq = EventSequencer("run-env")
    reducer = RunViewReducer(run_id="run-env")
    env = envelope_from_legacy(Event("turn_start", {"n": 2}), run_id="run-env", sequencer=seq)
    model = reducer.apply(env)
    assert model.turn == 2


def test_cockpit_render_and_review_panels() -> None:
    reducer = Reducer()
    reducer.apply_event(Event("agent_start", {"task": "ship feature"}))
    reducer.apply_event(Event("tool_end", {"tool": "write", "ok": True, "path": "a.py", "added": 3, "deleted": 1}))
    text = render_cockpit_text(reducer.model, cols=120, rows=40)
    plain = strip_ansi(text.plain)
    assert "ship feature" in plain and "Timeline" in plain
    review = ReviewState(files=[ChangeFile("a.py", 3, 1)], total_added=3, total_deleted=1, verified=False)
    changes = strip_ansi(render_changes_panel(review).plain)
    assert "a.py" in changes and "+3" in changes
    checks = [VerificationCheck("tests", "pass", "18/18")]
    ver = strip_ansi(render_verification_panel(checks, review).plain)
    assert "tests" in ver and "18/18" in ver


def test_tool_card_duration() -> None:
    assert format_duration_ms(450) == "450ms"
    assert format_duration_ms(1800) == "1.8s"
    line = render_tool_card_done("bash", ok=True, duration_ms=1800, summary="18 passed")
    assert "1.8s" in strip_ansi(line.plain)


def test_cockpit_full_layout_console() -> None:
    buf = StringIO()
    console = Console(file=buf, width=120, height=40, force_terminal=True, theme=KITE_THEME)
    reducer = Reducer()
    reducer.apply_event(Event("agent_start", {"task": "demo"}))
    from kite.ui.cockpit.render import render_cockpit

    render_cockpit(console, reducer.model, cols=120, rows=40)
    out = strip_ansi(buf.getvalue())
    assert "demo" in out and "Run" in out
