"""API style resolution — transport layer, not provider catalog."""

from __future__ import annotations

from kite.config import UserConfig
from kite.providers.resolve import resolve_model


def test_default_api_style_is_litellm_chat() -> None:
    resolved = resolve_model(provider="anthropic", model="claude-opus-5", config=UserConfig())
    assert resolved.api_style == "chat"

    resolved_openai = resolve_model(provider="openai", model="gpt-4o", config=UserConfig())
    assert resolved_openai.api_style == "chat"


def test_api_style_override_from_config(kite_home) -> None:
    cfg = UserConfig(
        api_styles={
            "anthropic": "messages",
            "openai": "responses",
            "openrouter": "chat",
        }
    )
    cfg.save()
    loaded = UserConfig.load()
    assert resolve_model(provider="anthropic", model="claude-opus-5", config=loaded).api_style == "messages"
    assert resolve_model(provider="openai", model="gpt-4o", config=loaded).api_style == "responses"
    assert resolve_model(provider="openrouter", model="meta-llama/llama-3", config=loaded).api_style == "chat"
