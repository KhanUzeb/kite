"""Paid web search/scrape providers — auto chain + Firecrawl fetch/crawl."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def test_search_provider_auto_order_prefers_tavily(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.tools.web_providers import resolve_search_engines

    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: "tvly-x")
    monkeypatch.setattr("kite.tools.web_providers.exa_api_key", lambda: "exa-x")
    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: "fc-x")
    assert resolve_search_engines("auto") == ["tavily", "exa", "firecrawl", "duckduckgo"]


def test_search_provider_auto_skips_missing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.tools.web_providers import resolve_search_engines

    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: None)
    monkeypatch.setattr("kite.tools.web_providers.exa_api_key", lambda: "exa-x")
    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: None)
    assert resolve_search_engines("auto") == ["exa", "duckduckgo"]


def test_websearch_uses_tavily_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.tools import web

    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: "tvly-test")
    monkeypatch.setattr("kite.tools.web_providers.exa_api_key", lambda: None)
    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: None)

    payload = {
        "results": [
            {
                "title": "Tavily Hit",
                "url": "https://example.com/a",
                "content": "Snippet from Tavily",
            }
        ]
    }

    def fake_json_post(url: str, *, headers=None, body=None, timeout=30):  # noqa: ANN001
        assert "tavily.com" in url
        assert headers.get("Authorization", "").startswith("Bearer ")
        return 200, payload

    monkeypatch.setattr("kite.tools.web_providers._http_json", fake_json_post)
    out = web.websearch("hello world", max_results=5)
    assert out["ok"] is True
    assert out["engine"] == "tavily"
    assert out["results"][0]["title"] == "Tavily Hit"
    assert "Tavily Hit" in out["output"]


def test_websearch_falls_back_when_paid_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.tools import web

    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: "tvly-bad")
    monkeypatch.setattr("kite.tools.web_providers.exa_api_key", lambda: None)
    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: None)

    def fail_json(*_a, **_k):  # noqa: ANN001
        return 401, {"error": "unauthorized"}

    monkeypatch.setattr("kite.tools.web_providers._http_json", fail_json)
    monkeypatch.setattr(web, "_ddg_instant", lambda q: [])
    monkeypatch.setattr(
        web,
        "_ddg_html_search",
        lambda q: (
            '<div class="result results_links results_links_deep web-result">'
            '<a class="result__a" href="https://example.com/ddg">DDG</a>'
            '<a class="result__snippet">fallback</a></div>',
            "html",
            None,
        ),
    )
    out = web.websearch("fallback query", max_results=3)
    assert out["ok"] is True
    assert out["engine"] == "duckduckgo"
    assert out["results"][0]["url"] == "https://example.com/ddg"


def test_webfetch_uses_firecrawl_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.tools import web

    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: "fc-test")

    def fake_json(url: str, *, headers=None, body=None, timeout=30):  # noqa: ANN001
        assert "firecrawl" in url and "scrape" in url
        return 200, {
            "success": True,
            "data": {
                "markdown": "# Hello\n\nWorld from Firecrawl",
                "metadata": {"title": "Hello", "description": "desc", "sourceURL": "https://example.com/"},
            },
        }

    monkeypatch.setattr("kite.tools.web_providers._http_json", fake_json)
    out = web.webfetch("https://example.com/")
    assert out["ok"] is True
    assert out.get("engine") == "firecrawl"
    assert "World from Firecrawl" in out["output"]
    assert out["title"] == "Hello"


def test_webcrawl_uses_firecrawl_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.tools import web

    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: "fc-test")

    calls: list[str] = []

    def fake_json(url: str, *, headers=None, body=None, timeout=30):  # noqa: ANN001
        calls.append(url)
        if url.endswith("/crawl"):
            return 200, {"success": True, "id": "job-1"}
        if "/crawl/job-1" in url:
            return 200, {
                "success": True,
                "status": "completed",
                "data": [
                    {
                        "markdown": "page one",
                        "metadata": {"sourceURL": "https://example.com/", "title": "Home"},
                    }
                ],
            }
        raise AssertionError(url)

    monkeypatch.setattr("kite.tools.web_providers._http_json", fake_json)
    out = web.webcrawl("https://example.com/", max_pages=2, max_depth=1)
    assert out["ok"] is True
    assert out.get("engine") == "firecrawl"
    assert "Home" in out["output"] or "page one" in out["output"]


def test_web_tool_key_aliases() -> None:
    from kite.tools.web_providers import resolve_web_tool_env

    assert resolve_web_tool_env("tavily") == "TAVILY_API_KEY"
    assert resolve_web_tool_env("exa") == "EXA_API_KEY"
    assert resolve_web_tool_env("firecrawl") == "FIRECRAWL_API_KEY"
    assert resolve_web_tool_env("unknown") is None
