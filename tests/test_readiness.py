"""Setup readiness and first-run detection."""

from __future__ import annotations

from kite.config.readiness import (
    assess_setup_status,
    has_config_file,
    is_fresh_install,
    needs_setup,
)
from kite.config import UserConfig


def test_fresh_install_without_config_or_keys(kite_home, monkeypatch) -> None:
    monkeypatch.setattr("kite.config.readiness.has_any_api_key", lambda: False)
    assert not has_config_file()
    assert is_fresh_install()
    assert needs_setup()


def test_not_fresh_when_config_exists(kite_home) -> None:
    cfg = UserConfig.load()
    cfg.default_provider = "groq"
    cfg.default_model = "llama-3.1-8b-instant"
    cfg.save()
    assert has_config_file()
    assert not is_fresh_install()


def test_ready_when_ollama_default_and_model_set(kite_home) -> None:
    cfg = UserConfig.load()
    cfg.default_provider = "ollama"
    cfg.default_model = "llama3.2"
    cfg.save()
    status = assess_setup_status()
    assert status.ready
    assert status.default_provider == "ollama"


def test_blockers_when_openai_default_no_key(kite_home, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    status = assess_setup_status()
    assert not status.ready
    assert status.blockers
    assert "openai" in status.blockers[0].lower() or "Missing" in status.blockers[0]
