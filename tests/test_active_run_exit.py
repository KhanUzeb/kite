"""Active-run stop/exit must be responsive, even at an approval gate.

The worker thread blocks inside ApprovalCoordinator.request() while the UI
waits for a decision. An interrupt alone cannot wake it, and a /quit that only
sets a flag lets a long turn (and its recovery auto-continue) run to completion
before the CLI exits. These tests drive the real REPL methods with fake work
and Events — no sleeps, no provider calls.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from kite.application.contracts import RunResult
from kite.ui.repl import ChatSession


@pytest.fixture
def chat(workspace, kite_home, monkeypatch):
    monkeypatch.setattr(ChatSession, "_warm_auth_probes", lambda self: None)
    monkeypatch.setattr("kite.models.litellm_model.prewarm_litellm", lambda: None)
    session = ChatSession(cwd=str(workspace), provider="groq", model="test")
    yield session
    session.display.close()


def test_stop_at_pending_approval_unblocks_worker_and_clears_gate(chat, monkeypatch) -> None:
    """Esc / /stop must resolve the parked approval, not just flag an interrupt."""
    from kite.application.policy import ApprovalCoordinator

    coord = ApprovalCoordinator(interactive=True)
    chat._approval_coordinator = coord
    chat.state.set_approval_request("bash", mandatory=True)
    harness = MagicMock()
    chat._harness = harness
    chat._busy = True

    pending = threading.Event()
    decisions: list[str] = []

    def _worker() -> None:
        pending.set()
        decisions.append(coord.request("bash", {"command": "long"}, mandatory=True))

    thread = threading.Thread(target=_worker, daemon=True, name="kite-approval-probe")
    thread.start()
    assert pending.wait(timeout=2), "worker must reach the approval gate"
    # Gate is really parked: no decision has been made yet.
    assert coord.pending is not None

    chat._slash_stop("")
    thread.join(timeout=2)

    assert not thread.is_alive(), "stop must wake the blocked worker immediately"
    assert decisions == ["stop"], decisions
    assert coord.pending is None
    assert not chat.state.awaiting_approval
    assert chat.state.interrupted
    harness.request_interrupt.assert_called_once()


def test_quit_during_turn_interrupts_tears_down_and_skips_recovery(chat, monkeypatch) -> None:
    """/quit mid-turn exits after the stop, without another recovery turn."""
    import kite.ui.complete as complete
    from kite.application import cli as app_cli

    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _execute(harness, task):  # noqa: ANN001
        calls.append("execute")
        entered.set()
        assert release.wait(timeout=2), "composer must release the fake turn"
        return RunResult(
            status="failed",
            stop_reason="interrupted",
            legacy={"exit_status": "Interrupted", "submission": ""},
        )

    def _busy_composer(**kwargs):  # noqa: ANN003
        assert entered.wait(timeout=2), "worker must be running"
        kwargs["on_eof"]()
        release.set()

    monkeypatch.setattr(app_cli, "execute_harness_task", _execute)
    monkeypatch.setattr(complete, "read_repl_busy_composer", _busy_composer)
    monkeypatch.setattr(chat, "_ensure_model_resolved", lambda: None)
    monkeypatch.setattr(chat, "_ensure_prompt", lambda: MagicMock())
    monkeypatch.setattr(chat, "_approver", lambda: MagicMock())
    monkeypatch.setattr(chat, "_wire_harness_git", lambda harness: None)
    monkeypatch.setattr(chat, "_bind_session", lambda harness: None)
    monkeypatch.setattr(chat, "_report_listener_failure", lambda harness: None)
    monkeypatch.setattr(chat, "_refresh_git_state", lambda *a, **k: None)
    monkeypatch.setattr(chat.display, "finish_composer_turn", lambda extra: None)

    harness = MagicMock(last_session=None)
    monkeypatch.setattr(chat, "_make_harness", lambda **kwargs: harness)
    chat.jobs = MagicMock()
    chat.jobs.kill_all.return_value = 1

    chat._run_task("do something long")

    assert chat._quit_after_turn is True
    assert calls == ["execute"], "quit must not start a recovery continuation"
    harness.request_interrupt.assert_called_once()
    chat.jobs.kill_all.assert_called_once()
    assert chat.state.active_jobs == 0
    assert chat.state.busy is False and chat._busy is False
    assert chat.state.interrupted


def test_run_exits_promptly_after_quit_flag(chat, monkeypatch) -> None:
    """The flag set mid-turn is consumed on the next loop tick, before prompts."""
    for name in (
        "_refresh_git_state",
        "_startup_banner",
        "_maybe_prompt_project_trust",
        "_schedule_release_check_legacy",
        "_prewarm_composer",
        "_print_resume_hint",
    ):
        monkeypatch.setattr(chat, name, lambda *a, **k: None)
    chat._quit_after_turn = True
    chat._read_input = lambda: (_ for _ in ()).throw(AssertionError("no prompt after quit"))  # type: ignore[method-assign]
    chat.jobs = MagicMock()
    chat.jobs.kill_all.return_value = 0

    assert chat.run() == 0
    chat.jobs.kill_all.assert_called_once()
