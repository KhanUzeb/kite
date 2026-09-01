"""Observation elision and compaction segment tests."""

from __future__ import annotations

from kite.context.observation import observation_content
from kite.context.window import compact_messages
from kite.memory.compaction_ops import run_compaction


def test_observation_prefers_summary_when_eliding() -> None:
    raw = "x" * 20_000
    out = observation_content(
        {"ok": True, "output": raw, "summary": "42 lines matched in src/app.py"},
        max_chars=2_000,
    )
    assert "42 lines matched" in out
    assert len(out) < len(raw)
    assert "elided" in out.lower()


def test_observation_small_output_unchanged() -> None:
    text = "hello world"
    assert observation_content({"output": text}, max_chars=8_000) == text


def test_compact_keeps_assistant_tool_pair() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a" * 500},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "read"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "file body"},
        {"role": "user", "content": "tail question"},
        {"role": "assistant", "content": "answer"},
    ]
    out = compact_messages(msgs, keep_recent_tokens=80, force=True)
    roles = [m["role"] for m in out]
    # Tail kept; if assistant+tool kept, they appear together
    if "tool" in roles:
        tool_idx = roles.index("tool")
        assert roles[tool_idx - 1] == "assistant"


def test_run_compaction_skips_llm_below_threshold() -> None:
    calls: list[str] = []

    def llm_summarizer(_dropped: list[dict]) -> str:
        calls.append("llm")
        return "llm summary"

    usage_ratio_msgs = [{"role": "user", "content": "word " * 20_000}] * 4
    msgs = [{"role": "system", "content": "s"}] + usage_ratio_msgs + [{"role": "user", "content": "z"}]
    result = run_compaction(
        msgs,
        window=128_000,
        reserve_tokens=16_384,
        keep_recent_tokens=500,
        force=True,
        summarizer=llm_summarizer,
        compaction_llm_ratio=0.99,
    )
    assert result.compacted
    assert calls == []
