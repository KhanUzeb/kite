"""Provider wire profiles + thinking clamp + approval poll idempotence."""

from __future__ import annotations

import pytest

from kite.models.reasoning import (
    ReasoningSupport,
    apply_reasoning,
    coerce_reasoning_for_model,
    detect_reasoning,
    thinking_level_menu,
)
from kite.providers.profiles import get_profile, normalize_effort


def _c_test_nvidia_profile_concrete_wire() -> None:
    prof = get_profile("nvidia")
    assert prof.reasoning_wire == "reasoning_effort"
    assert prof.allow_parallel_tools is False
    assert get_profile("nim").name == "nvidia"
    assert normalize_effort("nvidia", "HIGH") == "high"
    assert get_profile("unknown-xyz").reasoning_wire == "reasoning_effort"


def _c_test_nvidia_kwargs_never_emit_extra_body() -> None:
    support = detect_reasoning(
        "nvidia",
        "deepseek-ai/deepseek-r1",
        supported_parameters=["reasoning_effort"],
    )
    assert support.supported and support.can_thinking
    out = apply_reasoning({"model": "x", "messages": []}, support, "thinking")
    assert out.get("reasoning_effort") in {"medium", "high"}
    assert "extra_body" not in out or "reasoning" not in (out.get("extra_body") or {})
    off = apply_reasoning({"model": "x", "messages": []}, support, "off")
    assert off.get("reasoning_effort") == "none"


def _c_test_coerce_stale_thinking_on_model_switch() -> None:
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
    assert thinking_level_menu(info)
    assert coerce_reasoning_for_model("thinking:high", info) == "thinking:high"
    assert coerce_reasoning_for_model("thinking:xhigh", info) in {
        "thinking:high",
        "thinking:medium",
        "fast:low",
    }
    assert coerce_reasoning_for_model("thinking:high", None) == "auto"
    assert coerce_reasoning_for_model("auto", info) == "auto"


def _c_test_approval_poll_idempotent_no_touch_storm(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(
            provider="groq", model="test"
        ),
    )
    from kite.ui.repl import ChatSession

    chat = ChatSession(cwd=str(tmp_path))
    touches: list[str] = []
    orig_touch = chat.state.touch
    chat.state.touch = lambda *a, **k: touches.append("touch") or orig_touch(*a, **k)  # type: ignore[method-assign]
    chat._poll_pending_approval()
    chat._poll_pending_approval()
    assert touches == []


def test_batch_00() -> None:
    """Consolidated (bodies unchanged): test_nvidia_profile_concrete_wire, test_nvidia_kwargs_never_emit_extra_body."""
    _c_test_nvidia_profile_concrete_wire()
    _c_test_nvidia_kwargs_never_emit_extra_body()

def test_batch_01(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_coerce_stale_thinking_on_model_switch, test_approval_poll_idempotent_no_touch_storm."""
    _c_test_coerce_stale_thinking_on_model_switch()
    _mp1 = pytest.MonkeyPatch()
    try:
        _t1 = tmp_path / "t1_1"
        _t1.mkdir(parents=True, exist_ok=True)
        _c_test_approval_poll_idempotent_no_touch_storm(tmp_path=_t1, monkeypatch=_mp1)
    finally:
        _mp1.undo()

