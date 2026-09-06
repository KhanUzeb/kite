"""Unit tests for web search/fetch (no live network)."""

from __future__ import annotations

from unittest.mock import patch

from kite.tools import web

DDG_FIXTURE = """
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="https://example.com/docs">Example Docs</a>
  <a class="result__snippet">Official documentation for the example library.</a>
</div>
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ffoo">GitHub Repo</a>
  <a class="result__snippet">Source code on GitHub.</a>
</div>
"""

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Test Page Title</title></head>
<body>
<script>ignore me</script>
<main>
  <h1>Hello World</h1>
  <p>First paragraph of content.</p>
  <p>Second paragraph with <a href="/relative">link</a>.</p>
</main>
</body>
</html>
"""


def test_unwrap_ddg_redirect():
    wrapped = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ffoo%2Fbar"
    assert web.unwrap_tracking_url(wrapped) == "https://github.com/foo/bar"


def test_unwrap_google_redirect():
    wrapped = "https://www.google.com/url?q=https%3A%2F%2Fexample.com&sa=U"
    assert web.unwrap_tracking_url(wrapped) == "https://example.com"


def test_parse_ddg_html_regex():
    results = web._parse_ddg_html(DDG_FIXTURE, max_results=5)
    assert len(results) == 2
    assert results[0]["title"] == "Example Docs"
    assert results[0]["url"] == "https://example.com/docs"
    assert "documentation" in results[0]["snippet"]
    assert results[1]["url"] == "https://github.com/foo"


def test_parse_ddg_dedupes_urls():
    dup = DDG_FIXTURE + DDG_FIXTURE
    results = web._parse_ddg_html(dup, max_results=10)
    assert len(results) == 2


def test_extract_page_strips_scripts():
    title, text, links = web._extract_page(HTML_PAGE, "https://example.com/page")
    assert title == "Test Page Title"
    assert "ignore me" not in text
    assert "Hello World" in text
    assert "First paragraph" in text
    assert "https://example.com/relative" in links


def test_url_blocked_localhost():
    assert web._url_blocked("http://localhost/admin") is not None
    assert web._url_blocked("http://127.0.0.1/") is not None
    assert web._url_blocked("http://10.0.0.1/internal") is not None
    assert web._url_blocked("https://example.com") is None


@patch("kite.tools.web._fetch_url")
def test_webfetch_extracts_html(mock_fetch):
    mock_fetch.return_value = (HTML_PAGE.encode(), "text/html", None)
    out = web.webfetch("https://example.com/page", max_chars=10_000)
    assert out["ok"] is True
    assert out["title"] == "Test Page Title"
    assert "Hello World" in out["output"]
    assert "url: https://example.com/page" in out["output"]
    assert "<html" not in out["output"]


@patch("kite.tools.web._fetch_url")
def test_webfetch_json(mock_fetch):
    payload = b'{"name": "kite", "version": 1}'
    mock_fetch.return_value = (payload, "application/json", None)
    out = web.webfetch("https://example.com/data.json")
    assert out["ok"] is True
    assert '"name": "kite"' in out["output"]


@patch("kite.tools.web._fetch_url")
def test_webfetch_blocks_private(mock_fetch):
    out = web.webfetch("http://127.0.0.1/secret")
    assert out["ok"] is False
    mock_fetch.assert_not_called()


@patch("kite.tools.web._ddg_html_search")
def test_websearch_formats_output(mock_search):
    mock_search.return_value = (DDG_FIXTURE, None)
    out = web.websearch("example docs")
    assert out["ok"] is True
    assert out["count"] == 2
    assert "Example Docs" in out["output"]
    assert "https://example.com/docs" in out["output"]
