"""Setup wizard re-exports credential helpers."""

from __future__ import annotations

from kite.cli.setup import configured_providers


def test_configured_providers_includes_ollama_local() -> None:
    rows = configured_providers()
    ollama = next((r for r in rows if r[0] == "ollama"), None)
    assert ollama is not None
    assert ollama[1] is True
    assert ollama[2] == "local"
