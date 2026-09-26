"""Unit tests for web search/fetch (no live network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def test_tracking_unwrap_search_parse_and_dedupe():
    wrapped = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ffoo%2Fbar"
    assert web.unwrap_tracking_url(wrapped) == "https://github.com/foo/bar"
    google = "https://www.google.com/url?q=https%3A%2F%2Fexample.com&sa=U"
    assert web.unwrap_tracking_url(google) == "https://example.com"

    results = web._parse_ddg_html(DDG_FIXTURE, max_results=5)
    assert len(results) == 2
    assert results[0]["title"] == "Example Docs"
    assert results[0]["url"] == "https://example.com/docs"
    assert "documentation" in results[0]["snippet"]
    assert results[1]["url"] == "https://github.com/foo"

    lite = web._parse_ddg_html(DDG_LITE_FIXTURE, max_results=5)
    assert len(lite) == 2
    assert lite[0]["title"] == "Lite Result A"
    assert lite[0]["url"] == "https://lite.example.com/a"
    assert "Snippet for result A" in lite[0]["snippet"]

    dup = DDG_FIXTURE + DDG_FIXTURE
    assert len(web._parse_ddg_html(dup, max_results=10)) == 2

    instant = [{"title": "Example", "url": "https://example.com", "snippet": "instant"}]
    html = [{"title": "Example Docs", "url": "https://example.com", "snippet": "html"}]
    merged = web._merge_search_results(instant, html, max_results=5)
    assert len(merged) == 1
    assert merged[0]["snippet"] == "instant"


def test_page_extract_strips_scripts_and_sniffs_charset():
    title, description, text, links = web._extract_page(HTML_PAGE, "https://example.com/page")
    assert title == "Test Page Title"
    assert description == "A test page for extraction."
    assert "ignore me" not in text
    assert "Hello World" in text
    assert "First paragraph" in text
    assert "\n" in text
    assert "https://example.com/relative" in links

    raw = b'<html><head><meta charset="iso-8859-1"></head><body>ok</body></html>'
    assert web._meta_charset_sniff(raw) == "iso-8859-1"


@patch("kite.tools.web_providers.paid_websearch", return_value=None)
@patch("kite.tools.web._fetch_url")
@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_private_urls_blocked_everywhere(mock_search, mock_instant, mock_fetch, _mock_paid):
    assert web._url_blocked("http://localhost/admin") is not None
    assert web._url_blocked("http://127.0.0.1/") is not None
    assert web._url_blocked("http://10.0.0.1/internal") is not None
    assert web._url_blocked("https://example.com") is None

    out = web.webfetch("http://127.0.0.1/secret")
    assert out["ok"] is False
    mock_fetch.assert_not_called()

    mock_instant.return_value = [
        {"title": "Local", "url": "http://127.0.0.1/admin", "snippet": "blocked"},
    ]
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    searched = web.websearch("example docs")
    assert searched["ok"] is True
    assert searched["count"] == 2
    assert "127.0.0.1" not in searched["output"]

    page_with_private = """
    <html><body>
      <a href="https://example.com/public">Public</a>
      <a href="http://127.0.0.1/secret">Private</a>
    </body></html>
    """
    mock_fetch.return_value = (page_with_private.encode(), "text/html", "https://example.com/", None)
    crawled = web.webcrawl("https://example.com/", max_pages=3, max_depth=1)
    assert crawled["ok"] is True
    fetched = [call.args[0] for call in mock_fetch.call_args_list]
    assert "http://127.0.0.1/secret" not in fetched
    assert "https://example.com/public" in fetched


@patch("kite.tools.web._fetch_url")
def test_webfetch_modes_extract_links_json_preview_and_paging(mock_fetch):
    mock_fetch.return_value = (HTML_PAGE.encode(), "text/html", "https://example.com/page", None)
    out = web.webfetch("https://example.com/page", max_chars=10_000)
    assert out["ok"] is True
    assert out["title"] == "Test Page Title"
    assert out["description"] == "A test page for extraction."
    assert "Hello World" in out["output"]
    assert "url: https://example.com/page" in out["output"]
    assert "<html" not in out["output"]

    linked = web.webfetch("https://example.com/page", include_links=True)
    assert linked["ok"] is True
    assert "https://example.com/relative" in linked["output"]
    assert linked["links"]

    mock_fetch.return_value = (b'{"name": "kite", "version": 1}', "application/json", "https://example.com/data.json", None)
    as_json = web.webfetch("https://example.com/data.json")
    assert as_json["ok"] is True
    assert '"name": "kite"' in as_json["output"]

    mock_fetch.return_value = (HTML_PAGE.encode(), "text/html", "https://example.com/page", None)
    preview = web.webfetch("https://example.com/page", preview_only=True)
    assert preview["ok"] is True
    assert "preview_only: true" in preview["output"]
    assert "Hello World" not in preview["output"]
    assert preview.get("summary")

    paged = web.webfetch("https://example.com/page", start=0, max_lines=2, max_chars=5000)
    assert paged["ok"] is True
    assert paged["chars"] <= 500


@patch("kite.tools.web_providers.paid_websearch", return_value=None)
@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_output_modes_format_merge_empty_urls_compact(mock_search, mock_instant, _mock_paid):
    mock_instant.return_value = []
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    out = web.websearch("example docs")
    assert out["ok"] is True
    assert out["count"] == 2
    assert "Example Docs" in out["output"]
    assert "https://example.com/docs" in out["output"]
    assert out["source"] == "html"

    mock_instant.return_value = [
        {"title": "Instant", "url": "https://instant.example", "snippet": "from api"},
    ]
    merged = web.websearch("example docs", max_results=5)
    assert merged["ok"] is True
    assert merged["count"] == 3
    assert "Instant" in merged["output"]
    assert "Example Docs" in merged["output"]

    mock_instant.return_value = []
    mock_search.return_value = ("<html></html>", "html", None)
    empty = web.websearch("obscure query xyz")
    assert empty["ok"] is True
    assert empty["count"] == 0
    assert "No results found" in empty["output"]

    mock_search.return_value = (DDG_FIXTURE, "html", None)
    urls_only = web.websearch("example docs", urls_only=True)
    assert urls_only["ok"] is True
    assert "Example Docs" not in urls_only["output"]
    assert "https://example.com/docs" in urls_only["output"]
    assert urls_only.get("summary")

    compact = web.websearch("example docs", compact=True)
    assert compact["ok"] is True
    assert "Example Docs" in compact["output"]
    assert "Official documentation" not in compact["output"]


@patch("kite.tools.web._fetch_url")
def test_webcrawl_fails_when_every_fetch_fails(mock_fetch):
    mock_fetch.return_value = (b"", "text/html", "https://example.com/", "connection failed")
    out = web.webcrawl("https://example.com/", max_pages=2, max_depth=1)
    assert out["ok"] is False
    assert out["pages"] and out["pages"][0]["error"] == "connection failed"


def test_extract_drops_boilerplate_text_but_keeps_links():
    html = """<html><head><title>Page</title></head><body>
    <header><h1>Site Name</h1></header>
    <nav>Menu <a href="/docs">Docs</a> <a href="/api">API</a></nav>
    <main><p>Real article body.</p></main>
    <footer>Copyright 2026</footer></body></html>"""
    title, _, text, links = web._extract_page(html, "https://example.com/")
    assert title == "Page"
    assert "Real article body" in text
    assert "Menu" not in text and "Copyright" not in text and "Site Name" not in text
    assert "https://example.com/docs" in links
    assert "https://example.com/api" in links


@patch("kite.tools.web_providers._http_json")
def test_tavily_answer_surfaced(mock_http):
    from kite.tools.web_providers import search_tavily

    mock_http.return_value = (
        200,
        {
            "results": [{"title": "T", "url": "https://example.com/", "content": "snip"}],
            "answer": "42 is the answer",
        },
    )
    hit = search_tavily("ultimate question", max_results=5, api_key="k")
    assert hit is not None
    assert hit["answer"] == "42 is the answer"
    assert "answer: 42 is the answer" in hit["output"]


@patch("kite.tools.web_providers.paid_websearch")
@patch("kite.tools.web._ddg_instant")
@patch("kite.tools.web._ddg_html_search")
def test_websearch_tops_up_short_paid_results_and_notes_engine(mock_search, mock_instant, mock_paid):
    mock_paid.return_value = {
        "ok": True,
        "output": "paid",
        "summary": "s",
        "results": [{"title": "Paid", "url": "https://paid.example/", "snippet": "p"}],
        "count": 1,
        "engine": "tavily",
        "query": "q",
        "source": "api",
    }
    mock_instant.return_value = []
    mock_search.return_value = (DDG_FIXTURE, "html", None)
    out = web.websearch("q", max_results=5)
    assert out["engine"] == "tavily+duckduckgo"
    assert out["topped_up"] is True
    assert out["count"] > 1
    assert out["results"][0]["url"] == "https://paid.example/"
    assert "Example Docs" in out["output"]

    mock_paid.return_value = None
    with patch("kite.tools.web_providers.tavily_api_key", return_value=None):
        noted = web.websearch("example docs", engine="tavily", max_results=5)
    assert noted["engine"] == "duckduckgo"
    assert "tavily" in (noted.get("note") or "")
    assert "note:" in noted["output"]

    odd = web.websearch("example docs", engine="bogus", max_results=5)
    assert "unknown engine" in (odd.get("note") or "")


@patch("kite.tools.web_providers._http_json")
def test_tinyfish_search_parsing_and_auth_failures(mock_http):
    from kite.tools.web_providers import resolve_search_engines, search_tinyfish

    seen: dict[str, object] = {}

    def fake(url: str, *, headers=None, body=None, timeout=45):  # noqa: ANN001
        seen["url"] = url
        seen["headers"] = headers
        return 200, {
            "query": "q",
            "results": [
                {"position": 1, "site_name": "ex.com", "title": "Fish Hit", "snippet": "s", "url": "https://ex.com/fish"},
            ],
            "total_results": 1,
            "page": 0,
        }

    mock_http.side_effect = fake
    hit = search_tinyfish("q", max_results=5, api_key="tf-k")
    assert hit is not None and hit["engine"] == "tinyfish"
    assert hit["results"][0]["url"] == "https://ex.com/fish"
    assert str(seen["url"]).startswith("https://api.search.tinyfish.ai?query=")
    assert (seen["headers"] or {}).get("X-API-Key") == "tf-k"

    mock_http.side_effect = None
    mock_http.return_value = (401, {"error": "unauthorized"})
    assert search_tinyfish("q", max_results=5, api_key="bad") is None
    mock_http.return_value = (429, {"error": "rate limited"})
    assert search_tinyfish("q", max_results=5, api_key="k") is None

    with (
        patch("kite.tools.web_providers.tavily_api_key", return_value=None),
        patch("kite.tools.web_providers.exa_api_key", return_value="ex"),
        patch("kite.tools.web_providers.tinyfish_api_key", return_value="tf"),
        patch("kite.tools.web_providers.firecrawl_api_key", return_value=None),
    ):
        assert resolve_search_engines("auto") == ["exa", "tinyfish", "duckduckgo"]
        assert resolve_search_engines("tinyfish") == ["tinyfish", "duckduckgo"]


@patch("kite.tools.web._ddg_instant", return_value=[])
@patch("kite.tools.web._ddg_html_search", return_value=("", "", "offline"))
@patch("kite.tools.web_providers._http_json")
def test_websearch_tinyfish_preference(mock_http, _mock_search, _mock_instant):
    mock_http.return_value = (
        200,
        {"query": "q", "results": [{"title": "Fish", "url": "https://fish.example/", "snippet": "s"}]},
    )
    with (
        patch("kite.tools.web_providers.tavily_api_key", return_value=None),
        patch("kite.tools.web_providers.exa_api_key", return_value=None),
        patch("kite.tools.web_providers.tinyfish_api_key", return_value="tf-k"),
        patch("kite.tools.web_providers.firecrawl_api_key", return_value=None),
    ):
        out = web.websearch("q", max_results=5, engine="tinyfish")
    assert out["engine"] == "tinyfish"
    assert out["results"][0]["url"] == "https://fish.example/"

    with patch("kite.tools.web_providers.tinyfish_api_key", return_value=None):
        noted = web.websearch("q", max_results=5, engine="tinyfish")
    assert "TINYFISH_API_KEY" in (noted.get("note") or "")


@patch("kite.tools.web.time.sleep")
@patch("kite.tools.web._safe_opener")
def test_fetch_retries_transients_with_backoff(mock_opener_fn, mock_sleep):
    from urllib.error import URLError

    good = MagicMock()
    good.headers = {"Content-Type": "text/plain"}
    good.url = "https://example.com/"
    good.read.return_value = b"hello"
    good.__enter__.return_value = good
    opener = MagicMock()
    opener.open.side_effect = [URLError(OSError(104, "reset")), good]
    mock_opener_fn.return_value = opener
    raw, _ctype, final, err = web._fetch_url("https://example.com/", retries=1)
    assert err is None and raw == b"hello" and final == "https://example.com/"
    mock_sleep.assert_called_once()
