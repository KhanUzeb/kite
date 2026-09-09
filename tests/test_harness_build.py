"""Central harness config builder."""

from __future__ import annotations

from kite.agent.harness_build import build_harness_config


def test_build_harness_config_defaults() -> None:
    cfg = build_harness_config()
    assert cfg.mode == "build"
    assert cfg.approval == "auto"
    assert cfg.memory_in_prompt is False


def test_build_harness_config_repl_shape() -> None:
    cfg = build_harness_config(
        provider="groq",
        model_name="llama",
        cwd="/tmp/proj",
        mode="plan",
        approval="auto",
        interactive=True,
        execution_mode="host",
        memory_in_prompt=True,
        reasoning="fast",
    )
    assert cfg.provider == "groq"
    assert cfg.interactive is True
    assert cfg.memory_in_prompt is True
    assert cfg.reasoning == "fast"
