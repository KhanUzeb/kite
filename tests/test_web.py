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

DDG_LITE_FIXTURE = """
<table>
<tr><td><a class="result-link" href="https://lite.example.com/a">Lite Result A</a></td></tr>
<tr><td class="result-snippet">Snippet for result A.</td></tr>
<tr><td><a class="result-link" href="https://lite.example.com/b">Lite Result B</a></td></tr>
<tr><td class="result-snippet">Snippet for result B.</td></tr>
</table>
"""

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="description" content="A test page for extraction.">
  <meta property="og:title" content="OG Title Override">
  <title>Test Page Title</title>
</head>
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


def test_parse_ddg_lite_html():
    results = web._parse_ddg_html(DDG_LITE_FIXTURE, max_results=5)
    assert len(results) == 2
    assert results[0]["title"] == "Lite Result A"
    assert results[0]["url"] == "https://lite.example.com/a"
    assert "Snippet for result A" in results[0]["snippet"]


def test_parse_ddg_dedupes_urls():
    dup = DDG_FIXTURE + DDG_FIXTURE
    results = web._parse_ddg_html(dup, max_results=10)
    assert len(results) == 2


def test_merge_search_results_dedupes():
    instant = [{"title": "Example", "url": "https://example.com", "snippet": "instant"}]
    html = [{"title": "Example Docs", "url": "https://example.com", "snippet": "html"}]
    merged = web._merge_search_results(instant, html, max_results=5)
    assert len(merged) == 1
    assert merged[0]["snippet"] == "instant"


def test_extract_page_strips_scripts_and_preserves_blocks():
    title, description, text, links = web._extract_page(HTML_PAGE, "https://example.com/page")
    assert title == "Test Page Title"
    assert description == "A test page for extraction."
    assert "ignore me" not in text
    assert "Hello World" in text
    assert "First paragraph" in text
    assert "\n" in text
    assert "https://example.com/relative" in links


def test_meta_charset_sniff():
    raw = b'<html><head><meta charset="iso-8859-1"></head><body>ok</body></html>'
    assert web._meta_charset_sniff(raw) == "iso-8859-1"


def test_url_blocked_localhost():
    assert web._url_blocked("http://localhost/admin") is not None
    assert web._url_blocked("http://127.0.0.1/") is not None
    assert web._url_blocked("http://10.0.0.1/internal") is not None
    assert web._url_blocked("https://example.com") is None


@patch("kite.tools.web._fetch_url")
def test_webfetch_extracts_html(mock_fetch):
    mock_fetch.return_value = (HTML_PAGE.encode(), "text/html", "https://example.com/page", None)
    out = web.webfetch("https://example.com/page", max_chars=10_000)
    assert out["ok"] is True
    assert out["title"] == "Test Page Title"
    assert out["description"] == "A test page for extraction."
    assert "Hello World" in out["output"]
    assert "url: https://example.com/page" in out["output"]
    assert "<html" not in out["output"]


@patch("kite.tools.web._fetch_url")
def test_webfetch_include_links(mock_fetch):
    mock_fetch.return_value = (HTML_PAGE.encode(), "text/html", "https://example.com/page", None)
    out = web.webfetch("https://example.com/page", include_links=True)
    assert out["ok"] is True
    assert "https://example.com/relative" in out["output"]
    assert out["links"]


@patch("kite.tools.web._fetch_url")
def test_webfetch_json(mock_fetch):
    payload = b'{"name": "kite", "version": 1}'
    mock_fetch.return_value = (payload, "application/json", "https://example.com/data.json", None)
    out = web.webfetch("https://example.com/data.json")
    assert out["ok"] is True
    assert '"name": "kite"' in out["output"]


@patch("kite.tools.web._fetch_url")
def test_webfetch_blocks_private(mock_fetch):
    out = web.webfetch("http://127.0.0.1/secret")
    assert out["ok"] is False
    mock_fetch.assert_not_called()


@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_formats_output(mock_search, mock_instant):
    mock_instant.return_value = []
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    out = web.websearch("example docs")
    assert out["ok"] is True
    assert out["count"] == 2
    assert "Example Docs" in out["output"]
    assert "https://example.com/docs" in out["output"]
    assert out["source"] == "html"


@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_merges_instant_and_html(mock_search, mock_instant):
    mock_instant.return_value = [
        {"title": "Instant", "url": "https://instant.example", "snippet": "from api"},
    ]
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    out = web.websearch("example docs", max_results=5)
    assert out["ok"] is True
    assert out["count"] == 3
    assert "Instant" in out["output"]
    assert "Example Docs" in out["output"]


@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_empty_hint(mock_search, mock_instant):
    mock_instant.return_value = []
    mock_search.return_value = ("<html></html>", "html", None)
    out = web.websearch("obscure query xyz")
    assert out["ok"] is True
    assert out["count"] == 0
    assert "No results found" in out["output"]


@patch("kite.tools.web._fetch_url")
def test_webfetch_preview_only(mock_fetch):
    mock_fetch.return_value = (HTML_PAGE.encode(), "text/html", "https://example.com/page", None)
    out = web.webfetch("https://example.com/page", preview_only=True)
    assert out["ok"] is True
    assert "preview_only: true" in out["output"]
    assert "Hello World" not in out["output"]
    assert out.get("summary")


@patch("kite.tools.web._fetch_url")
def test_webfetch_start_and_max_lines(mock_fetch):
    mock_fetch.return_value = (HTML_PAGE.encode(), "text/html", "https://example.com/page", None)
    out = web.webfetch("https://example.com/page", start=0, max_lines=2, max_chars=5000)
    assert out["ok"] is True
    assert out["chars"] <= 500


@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_urls_only(mock_search, mock_instant):
    mock_instant.return_value = []
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    out = web.websearch("example docs", urls_only=True)
    assert out["ok"] is True
    assert "Example Docs" not in out["output"]
    assert "https://example.com/docs" in out["output"]
    assert out.get("summary")


@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_compact(mock_search, mock_instant):
    mock_instant.return_value = []
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    out = web.websearch("example docs", compact=True)
    assert out["ok"] is True
    assert "Example Docs" in out["output"]
    assert "Official documentation" not in out["output"]


@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_filters_private_urls(mock_search, mock_instant):
    mock_instant.return_value = [
        {"title": "Local", "url": "http://127.0.0.1/admin", "snippet": "blocked"},
    ]
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    out = web.websearch("example docs")
    assert out["ok"] is True
    assert out["count"] == 2
    assert "127.0.0.1" not in out["output"]


@patch("kite.tools.web._fetch_url")
def test_webcrawl_skips_private_links(mock_fetch):
    page_with_private = """
    <html><body>
      <a href="https://example.com/public">Public</a>
      <a href="http://127.0.0.1/secret">Private</a>
    </body></html>
    """
    mock_fetch.return_value = (page_with_private.encode(), "text/html", "https://example.com/", None)
    out = web.webcrawl("https://example.com/", max_pages=3, max_depth=1)
    assert out["ok"] is True
    fetched = [call.args[0] for call in mock_fetch.call_args_list]
    assert "http://127.0.0.1/secret" not in fetched
    assert "https://example.com/public" in fetched
