"""Provider wire profiles + thinking clamp + approval poll idempotence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from kite.models.reasoning import (
    ReasoningSupport,
    apply_reasoning,
    coerce_reasoning_for_model,
    detect_reasoning,
)


def test_nvidia_kwargs_never_emit_extra_body(monkeypatch) -> None:
    monkeypatch.setattr("kite.models.reasoning._cache", {})
    monkeypatch.setattr("kite.models.reasoning._params_from_litellm", lambda *_: set())
    support = detect_reasoning(
        "nvidia",
        "deepseek-ai/deepseek-r1",
        supported_parameters=["reasoning_effort"],
        litellm_model="nvidia/deepseek-ai/deepseek-r1",
    )
    assert support.supported and support.can_thinking
    out = apply_reasoning({"model": "x", "messages": []}, support, "thinking")
    assert out.get("reasoning_effort") in {"medium", "high"}
    assert "extra_body" not in out or "reasoning" not in (out.get("extra_body") or {})
    off = apply_reasoning({"model": "x", "messages": []}, support, "off")
    assert off.get("reasoning_effort") == "none"


def test_coerce_stale_thinking_on_model_switch() -> None:
    info = ReasoningSupport(
        supported=True,
        can_fast=True,
        can_thinking=True,
        can_disable=True,
        thinking_kwargs={"reasoning_effort": "high"},
        fast_kwargs={"reasoning_effort": "low"},
        off_kwargs={"reasoning_effort": "none"},
        efforts=("none", "low", "medium", "high"),
    )
    assert coerce_reasoning_for_model("thinking:high", info) == "thinking:high"
    assert coerce_reasoning_for_model("thinking:xhigh", info) == "thinking:high"
    assert coerce_reasoning_for_model("thinking:high", None) == "auto"
    assert coerce_reasoning_for_model("auto", info) == "auto"


def test_approval_poll_invalidates_only_on_state_transitions(monkeypatch) -> None:
    from kite.ui.repl import ChatSession
    from kite.ui.state import SessionUiState

    # Polling needs only approval/UI state, not ChatSession's model warmup threads.
    chat = ChatSession.__new__(ChatSession)
    chat.state = SessionUiState()
    chat._approval_coordinator = SimpleNamespace(pending=None)
    chat._approval_wake_sent = False
    touches = Mock(wraps=chat.state.touch)
    wake = Mock()
    monkeypatch.setattr(chat.state, "touch", touches)
    monkeypatch.setattr(chat, "_prompt_app_running", lambda: True)
    monkeypatch.setattr(chat, "_wake_composer", wake)

    chat._poll_pending_approval()
    chat._poll_pending_approval()
    touches.assert_not_called()
    wake.assert_not_called()

    chat._approval_coordinator.pending = SimpleNamespace(tool="bash", mandatory=True)
    chat._poll_pending_approval()
    chat._poll_pending_approval()
    assert chat.state.awaiting_approval == "bash"
    assert chat.state.awaiting_approval_mandatory is True
    touches.assert_called_once_with()
    wake.assert_called_once_with()

    touches.reset_mock()
    chat._approval_coordinator.pending = None
    chat._poll_pending_approval()
    chat._poll_pending_approval()
    assert chat.state.awaiting_approval == ""
    assert chat.state.awaiting_approval_mandatory is False
    assert chat._approval_wake_sent is False
    touches.assert_called_once_with(force=True)
