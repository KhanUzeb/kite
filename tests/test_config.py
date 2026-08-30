"""Runtime config loading."""

from __future__ import annotations

from kite.config.runtime import load_runtime_config


def test_default_config_loads_trusted_paths_and_cache() -> None:
    cfg = load_runtime_config()
    assert isinstance(cfg.guardrails.trusted_paths, list)
    assert cfg.prompt_cache_enabled is True
    assert cfg.orchestrator_max_workers >= 1
