"""Runtime config loading."""

from __future__ import annotations

from kite.config.runtime import load_runtime_config


def test_default_config_loads_trusted_paths_and_cache() -> None:
    cfg = load_runtime_config()
    assert isinstance(cfg.guardrails.trusted_paths, list)
    assert cfg.prompt_cache_enabled is True
    assert cfg.orchestrator_max_workers >= 1
    assert cfg.ui_theme == "auto"
    assert cfg.ui_font == "unicode"


def test_runtime_config_cache_returns_same_object() -> None:
    assert load_runtime_config() is load_runtime_config()


def test_catalog_cache_returns_same_object() -> None:
    from kite.providers.catalog import load_catalog

    assert load_catalog() is load_catalog()
