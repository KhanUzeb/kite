"""Slash completer for /models — real model ids, not select/provider loops."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kite.ui.complete import SlashCompleter, _PT


class _Doc:
    def __init__(self, text: str) -> None:
        self.text_before_cursor = text


@pytest.fixture
def completer() -> SlashCompleter:
    return SlashCompleter(
        index_factory=lambda: MagicMock(specs={}, skills=[], plugins=[]),
        models_factory=lambda provider=None: (
            ["llama3.2", "mistral"] if provider == "ollama" else ["gpt-4o", "o3"]
        ),
        providers_factory=lambda: ["ollama", "chatgpt", "groq"],
    )


@pytest.mark.skipif(not _PT, reason="prompt_toolkit unavailable")
def test_models_completes_providers_first(completer: SlashCompleter) -> None:
    hits = list(completer.get_completions(_Doc("/models "), None))
    values = [c.text for c in hits]
    assert "refresh" in values
    assert "ollama" in values
    assert "select" not in values
    assert "provider" not in values


@pytest.mark.skipif(not _PT, reason="prompt_toolkit unavailable")
def test_models_after_provider_completes_model_ids(completer: SlashCompleter) -> None:
    hits = list(completer.get_completions(_Doc("/models ollama "), None))
    values = [c.text for c in hits]
    assert values == ["llama3.2", "mistral"]
    assert "select" not in values
    assert "chatgpt" not in values


@pytest.mark.skipif(not _PT, reason="prompt_toolkit unavailable")
def test_model_bare_offers_verbs_and_ids(completer: SlashCompleter) -> None:
    hits = list(completer.get_completions(_Doc("/model "), None))
    values = [c.text for c in hits]
    assert "list" in values
    assert "select" in values
    assert "gpt-4o" in values
    # Not stuck offering only verbs repeatedly as the only options
    assert values.count("select") == 1
