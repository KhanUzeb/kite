"""SessionUiState repaint throttle, flash TTL, and context-window safety."""

from __future__ import annotations

import time

import pytest

from kite.ui.complete import _toolbar_html
from kite.ui.state import SessionUiState


class _Clock:
    """Monotonic clock stub — no sleeps, so throttle windows are deterministic."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _recording_state(clock: _Clock) -> tuple[SessionUiState, list[float]]:
    """State whose ``_refresh`` records the clock value it was invoked at."""
    state = SessionUiState()
    paints: list[float] = []
    state._refresh = lambda: paints.append(clock.now)  # noqa: SLF001
    return state, paints


def test_throttled_touch_defers_and_flush_pending_touch_delivers(monkeypatch) -> None:
    """A second touch inside the window must not repaint; the drain must."""
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    state, paints = _recording_state(clock)

    state.set_context_usage(total_tokens=100, window=1000)
    assert len(paints) == 1, "the first paint of a session is never throttled"

    clock.advance(0.01)
    state.set_context_usage(total_tokens=900, window=1000)
    assert len(paints) == 1, "0.01s after the last paint the update must be deferred"
    assert state._touch_pending is True  # noqa: SLF001
    assert state.tokens == 900, "the deferred update is already committed to state"

    state.flush_pending_touch()
    assert len(paints) == 2, "the drain must deliver the deferred paint"
    assert state._touch_pending is False  # noqa: SLF001

    state.flush_pending_touch()
    assert len(paints) == 2, "draining twice must not repaint an already-painted footer"


def test_turn_boundary_clear_running_is_never_throttled_away(monkeypatch) -> None:
    """The last touch of a turn must repaint, or the footer freezes on "working".

    A turn ends microseconds after its last streamed paint, so the boundary
    ``clear_running()`` lands inside the throttle window. The only
    ``flush_pending_touch()`` call lives in ``ChatSession._drain_ui_queue``,
    which runs before that boundary and not again until the next turn — so a
    throttled boundary leaves the on-screen running line frozen until the user
    types something.
    """
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    state, paints = _recording_state(clock)
    state.busy = True

    state.set_running(label="working  bash  4s", kind="bash")
    clock.advance(0.2)
    state.set_activity_preview("pytest -q")
    assert paints == [1000.0, 1000.2], "a running turn paints continuously"

    clock.advance(0.02)  # the turn ended 20ms after the last streamed paint
    state.busy = False
    state.clear_running()

    assert state.running_label == "", "the running line is cleared in state"
    assert paints[-1] == clock.now, "the turn boundary itself must reach the footer"
    assert state._touch_pending is False  # noqa: SLF001


def test_flash_is_never_swallowed_by_the_repaint_throttle(monkeypatch) -> None:
    """A flash is a one-shot notification, so the rate limiter must not eat it.

    Nothing drains ``_touch_pending`` while the composer is idle (the only
    ``flush_pending_touch()`` call lives in ``ChatSession._drain_ui_queue``,
    reachable only from the busy-turn pollers), so a flash set inside the
    throttle window never reaches the toolbar.
    """
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    state, paints = _recording_state(clock)

    state.touch(force=True)
    assert len(paints) == 1

    clock.advance(0.01)
    state.set_flash("queued 1  check the failing test")

    assert state.flash == "queued 1  check the failing test"
    assert len(paints) == 2, "a flash set inside the throttle window must still repaint"
    assert state._touch_pending is False  # noqa: SLF001


def test_flash_expires_after_its_ttl_while_the_ui_sits_idle(monkeypatch) -> None:
    """Expiry is checked on read: nothing calls touch() for 8s at the prompt."""
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    state, _paints = _recording_state(clock)

    state.set_flash("restored queued messages to composer")
    assert state.active_flash == "restored queued messages to composer"
    assert "restored queued messages to composer" in str(_toolbar_html(state))

    clock.advance(8.5)  # idle at the prompt: no touch(), no busy turn

    # Reading through the accessor is what expires it; touch() never runs here.
    assert state.active_flash == "", "an expired flash must not stay on the footer forever"
    assert state.flash == "", "expiry must clear the field, not just hide the read"
    assert state.flash_at is None


def test_context_pct_is_safe_for_nonpositive_and_overfull_windows() -> None:
    """A misconfigured ``context_window = -1`` must not render as ctx -800%."""
    state = SessionUiState()

    state.set_context_usage(total_tokens=8000, window=0)
    assert state.context_pct is None

    state.set_context_usage(total_tokens=8000, window=-1)
    assert state.context_pct is None, "a non-positive window is unknown, not a ratio"

    state.set_context_usage(total_tokens=8000, window=1000)
    assert state.context_pct == 1.0, "an overfull context clamps at 100%"

    state.set_context_usage(total_tokens=500, window=1000)
    assert state.context_pct == pytest.approx(0.5)