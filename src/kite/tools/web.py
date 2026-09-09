"""Free web search and fetch — no API keys required (stdlib urllib).

websearch: DuckDuckGo HTML results (+ instant API fallback).
webfetch:  fetch one URL and return extracted readable text (not raw HTML soup).
webcrawl:  same-origin crawl with depth/page limits.
"""

from __future__ import annotations

import html
import json
import re
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from kite.guardrails.ssrf import (
    build_safe_opener,
    guarded_request,
    validate_request_url,
)
from kite.guardrails.ssrf import (
    url_blocked as _url_blocked,
)

try:
    from kite import __version__
except Exception:  # pragma: no cover
    __version__ = "0.9.1"

_USER_AGENT = f"kite-agent/{__version__} (+https://github.com/KhanUzeb/kite)"
_MAX_BODY = 120_000
_FETCH_TIMEOUT = 20
_MAX_FETCH_TIMEOUT = 45
_DEFAULT_FETCH_CHARS = 24_000
_MAX_REDIRECTS = 5
_CRAWL_MAX_SECONDS = 90
_CRAWL_MAX_TOTAL_BYTES = 500_000


def _safe_opener():
    return build_safe_opener(max_redirects=_MAX_REDIRECTS)


def _url_allowed(url: str) -> bool:
    return _url_blocked(url) is None


def _urlencode(text: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(text)


def unwrap_tracking_url(url: str) -> str:
    """Resolve DuckDuckGo / Google redirect wrappers to the destination URL."""
    text = (url or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    if "duckduckgo.com" in host and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            candidate = unquote(target)
            if _url_allowed(candidate):
                return candidate
    if host.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q", [None])[0]
        if target:
            candidate = unquote(target)
            if _url_allowed(candidate):
                return candidate
    return text


def _is_transient_fetch_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, OSError)):
            err_no = getattr(reason, "errno", None)
            if err_no in {110, 111, 104}:  # ETIMEDOUT, ECONNREFUSED, ECONNRESET
                return True
    if isinstance(exc, OSError):
        if exc.errno in {110, 111, 104}:
            return True
    return False


def _fetch_url(
    url: str,
    *,
    timeout: int = _FETCH_TIMEOUT,
    max_bytes: int = _MAX_BODY,
    retries: int = 1,
) -> tuple[bytes, str, str, str | None]:
    """Return (raw_bytes, content_type, final_url, error)."""
    err = _url_blocked(url)
    if err:
        return b"", "", url, err

    timeout = min(max(1, int(timeout)), _MAX_FETCH_TIMEOUT)
    last_err: str | None = None
    attempts = max(0, int(retries)) + 1
    for attempt in range(attempts):
        try:
            req = guarded_request(
                url,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
                },
            )
            err = validate_request_url(url)
            if err:
                return b"", "", url, err
            with _safe_opener().open(req, timeout=timeout) as resp:  # noqa: S310
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                final_url = getattr(resp, "url", None) or url
                post_err = validate_request_url(final_url)
                if post_err:
                    return b"", "", final_url, post_err
                return resp.read(max_bytes), ctype, final_url, None
        except (URLError, OSError, TimeoutError, ValueError) as e:
            last_err = str(e)
            if attempt + 1 < attempts and _is_transient_fetch_error(e):
                continue
            return b"", "", url, last_err
    return b"", "", url, last_err


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _collapse_inline_ws(text: str) -> str:
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _clean_block_text(text: str) -> str:
    lines = [_collapse_inline_ws(line) for line in text.splitlines()]
    cleaned = [line for line in lines if line]
    return "\n".join(cleaned).strip()


def _meta_charset_sniff(raw: bytes) -> str | None:
    head = raw[:4096].decode("latin-1", errors="ignore")
    match = re.search(
        r'<meta[^>]+charset=["\']?([a-zA-Z0-9_-]+)',
        head,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    match = re.search(
        r'<meta[^>]+content=["\'][^"\']*charset=([a-zA-Z0-9_-]+)',
        head,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.title = ""
        self.og_title = ""
        self.description = ""
        self._in_title = False
        self.text_parts: list[str] = []
        self._skip_tags = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip_tags += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            name = (attr.get("name") or attr.get("property") or "").lower()
            content = (attr.get("content") or "").strip()
            if content:
                if name in {"description", "og:description"} and not self.description:
                    self.description = content
                elif name == "og:title" and not self.og_title:
                    self.og_title = content
        if tag == "a":
            href = attr.get("href")
            if href:
                self.links.append(href)
        if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "code", "article", "main", "td", "th", "br"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_tags:
            self._skip_tags -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "article", "main"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_tags:
            return
        if self._in_title:
            self.title += data
        else:
            self.text_parts.append(data)


def _extract_page(body: str, base_url: str) -> tuple[str, str, str, list[str]]:
    """Return (title, description, text, absolute_links)."""
    parser = _LinkExtractor()
    try:
        parser.feed(body)
    except Exception:
        pass
    title = _collapse_inline_ws(parser.title) or _collapse_inline_ws(parser.og_title)
    description = _collapse_inline_ws(parser.description)
    text = _clean_block_text("".join(parser.text_parts))
    if not text:
        text = _clean_block_text(_strip_tags(body))
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        abs_url = unwrap_tracking_url(urljoin(base_url, href))
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        key = parsed._replace(fragment="").geturl()
        if key not in seen:
            seen.add(key)
            links.append(key)
    return title, description, text, links


def _decode_body(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].strip() or charset
    else:
        sniffed = _meta_charset_sniff(raw)
        if sniffed:
            charset = sniffed
    return raw.decode(charset, errors="replace")


def _format_json_text(raw: bytes, *, max_chars: int) -> str:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")[:max_chars]
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n…[truncated]…"
    return text


def _truncate_middle(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    head = int(max_chars * 0.65)
    tail = max_chars - head - 24
    return text[:head] + "\n…[truncated]…\n" + text[-tail:], True


def _result_key(url: str) -> str:
    return urlparse(url)._replace(fragment="").geturl()


def _merge_search_results(
    *groups: list[dict[str, str]],
    max_results: int,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for hit in group:
            url = (hit.get("url") or "").strip()
            title = (hit.get("title") or "").strip()
            if not title and not url:
                continue
            key = _result_key(url) if url else f"title:{title.lower()}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "title": title or url or "(no title)",
                    "url": url,
                    "snippet": (hit.get("snippet") or "").strip(),
                }
            )
            if len(merged) >= max_results:
                return merged
    return merged


def webfetch(
    url: str,
    *,
    timeout: int = _FETCH_TIMEOUT,
    max_chars: int = _DEFAULT_FETCH_CHARS,
    extract: bool = True,
    include_links: bool = False,
    max_links: int = 12,
) -> dict[str, Any]:
    """Fetch one URL and return readable text (HTML stripped by default)."""
    target = unwrap_tracking_url(url.strip())
    err = _url_blocked(target)
    if err:
        return {"ok": False, "error": err, "output": err, "url": target}

    raw, content_type, final_url, fetch_err = _fetch_url(target, timeout=max(1, int(timeout)))
    if fetch_err:
        return {"ok": False, "error": fetch_err, "output": fetch_err, "url": target}

    max_chars = max(500, min(int(max_chars), 80_000))
    max_links = max(1, min(int(max_links), 30))
    title = ""
    description = ""
    outbound_links: list[str] = []
    truncated = False

    if content_type.startswith("application/json") or target.endswith(".json"):
        text = _format_json_text(raw, max_chars=max_chars)
    elif extract and ("html" in content_type or "<html" in raw[:500].lower()):
        body = _decode_body(raw, content_type)
        title, description, text, outbound_links = _extract_page(body, final_url)
        text, truncated = _truncate_middle(text, max_chars)
    else:
        text = _decode_body(raw, content_type)
        text, truncated = _truncate_middle(text, max_chars)

    lines = [
        f"url: {final_url}",
    ]
    if final_url != target:
        lines.append(f"requested: {target}")
    lines.extend(
        [
            f"content-type: {content_type or 'unknown'}",
            f"chars: {len(text)}",
        ]
    )
    if title:
        lines.append(f"title: {title}")
    if description:
        lines.append(f"description: {description}")
    if truncated:
        lines.append("truncated: true")
    if include_links and outbound_links:
        lines.append(f"links: {len(outbound_links)}")
        for link in outbound_links[:max_links]:
            lines.append(f"  - {link}")
        if len(outbound_links) > max_links:
            lines.append(f"  … and {len(outbound_links) - max_links} more")
    lines.extend(["", text])
    output = "\n".join(lines).strip()

    return {
        "ok": True,
        "output": output,
        "url": final_url,
        "requested_url": target,
        "title": title,
        "description": description,
        "content_type": content_type,
        "truncated": truncated,
        "chars": len(text),
        "links": outbound_links[:max_links] if include_links else [],
    }


class _DDGResultParser(HTMLParser):
    """Fallback parser when DDG HTML layout shifts away from legacy regex."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result = False
        self._capture: str | None = None
        self._current: dict[str, str] = {}
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if tag == "div" and "web-result" in classes:
            self._in_result = True
            self._current = {}
            return
        if not self._in_result:
            return
        if tag == "a":
            cls = classes
            href = dict(attrs).get("href") or ""
            if "result__a" in cls or "result-link" in cls:
                self._capture = "url"
                self._buf = []
                if href:
                    self._current["url"] = unwrap_tracking_url(href)
            elif "result__snippet" in cls or "result-snippet" in cls:
                self._capture = "snippet"
                self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_result and self._capture is None and self._current.get("url"):
            title = self._current.get("title") or self._current.get("url")
            self.results.append(
                {
                    "title": title,
                    "url": self._current["url"],
                    "snippet": self._current.get("snippet", ""),
                }
            )
            self._in_result = False
            self._current = {}
            return
        if tag == "a" and self._capture:
            text = _normalize_ws("".join(self._buf))
            if self._capture == "url" and text and "title" not in self._current:
                self._current["title"] = text
            elif self._capture == "snippet":
                self._current["snippet"] = text
            self._capture = None
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)


class _DDGLiteParser(HTMLParser):
    """Parser for lite.duckduckgo.com table layout."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._pending_title = ""
        self._pending_url = ""
        self._capture_snippet = False
        self._snippet_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        classes = attr.get("class", "")
        if tag == "a" and ("result-link" in classes or "result__a" in classes):
            href = attr.get("href") or ""
            self._pending_url = unwrap_tracking_url(href) if href else ""
            self._pending_title = ""
            self._capture_snippet = False
            return
        if tag == "td" and "result-snippet" in classes:
            self._capture_snippet = True
            self._snippet_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._pending_url:
            title = _normalize_ws(self._pending_title)
            if title or self._pending_url:
                self.results.append(
                    {
                        "title": title or self._pending_url,
                        "url": self._pending_url,
                        "snippet": "",
                    }
                )
            self._pending_title = ""
            self._pending_url = ""
            return
        if tag == "td" and self._capture_snippet:
            snippet = _normalize_ws("".join(self._snippet_buf))
            if snippet and self.results:
                self.results[-1]["snippet"] = snippet
            self._capture_snippet = False
            self._snippet_buf = []

    def handle_data(self, data: str) -> None:
        if self._pending_url and not self._capture_snippet:
            self._pending_title += data
        if self._capture_snippet:
            self._snippet_buf.append(data)


def _parse_ddg_lite(body: str, max_results: int) -> list[dict[str, str]]:
    lite = _DDGLiteParser()
    try:
        lite.feed(body)
    except Exception:
        pass
    return lite.results[:max_results]


def _parse_ddg_html(body: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML result blocks."""
    if 'class="result-snippet"' in body:
        lite_results = _parse_ddg_lite(body, max_results)
        if lite_results:
            return lite_results

    patterns = (
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result-snippet"[^>]*>(.*?)</a>',
        r'class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    )
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(url_raw: str, title_raw: str, snippet_raw: str = "") -> None:
        url = unwrap_tracking_url(_normalize_ws(_strip_tags(url_raw)))
        if url.startswith("//"):
            url = "https:" + url
        title = _normalize_ws(_strip_tags(title_raw))
        snippet = _normalize_ws(_strip_tags(snippet_raw))
        if not url or not title:
            return
        key = _result_key(url)
        if key in seen:
            return
        seen.add(key)
        results.append({"title": title, "url": url, "snippet": snippet})

    for pattern in patterns:
        for block in re.findall(pattern, body, flags=re.DOTALL | re.IGNORECASE):
            if len(block) == 2:
                _add(block[0], block[1])
            else:
                _add(block[0], block[1], block[2])
            if len(results) >= max_results:
                return results[:max_results]

    if not results:
        parser = _DDGResultParser()
        try:
            parser.feed(body)
        except Exception:
            pass
        for hit in parser.results:
            key = _result_key(hit["url"])
            if key in seen:
                continue
            seen.add(key)
            results.append(hit)
            if len(results) >= max_results:
                break

    if not results and "lite.duckduckgo.com" in body:
        for hit in _parse_ddg_lite(body, max_results):
            key = _result_key(hit["url"])
            if key in seen:
                continue
            seen.add(key)
            results.append(hit)
            if len(results) >= max_results:
                break

    return results[:max_results]


def _ddg_instant(query: str) -> list[dict[str, str]]:
    url = f"https://api.duckduckgo.com/?q={_urlencode(query)}&format=json&no_html=1&skip_disambig=1"
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    hits: list[dict[str, str]] = []
    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read(32_000).decode("utf-8", errors="replace"))
    except Exception:
        return hits

    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = unwrap_tracking_url((data.get("AbstractURL") or "").strip())
    heading = (data.get("Heading") or query).strip()
    if abstract:
        hits.append({"title": heading, "url": abstract_url, "snippet": abstract})

    for item in data.get("RelatedTopics") or []:
        if not isinstance(item, dict):
            continue
        text = (item.get("Text") or "").strip()
        if not text:
            if "Topics" in item:
                for sub in item.get("Topics") or []:
                    if isinstance(sub, dict) and sub.get("Text"):
                        hits.append(
                            {
                                "title": heading,
                                "url": unwrap_tracking_url(str(sub.get("FirstURL") or "")),
                                "snippet": str(sub["Text"])[:400],
                            }
                        )
            continue
        hits.append(
            {
                "title": heading,
                "url": unwrap_tracking_url(str(item.get("FirstURL") or "")),
                "snippet": text[:400],
            }
        )
    return hits


def _ddg_html_search(query: str) -> tuple[str | None, str, str | None]:
    """Return (html_body, source, error). Tries POST html endpoint, then GET lite."""
    data = f"q={_urlencode(query)}".encode()
    post_req = Request(
        "https://html.duckduckgo.com/html/",
        data=data,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(post_req, timeout=_FETCH_TIMEOUT) as resp:  # noqa: S310
            return resp.read(_MAX_BODY).decode("utf-8", errors="replace"), "html", None
    except (URLError, OSError, TimeoutError, ValueError):
        pass

    get_req = Request(
        f"https://lite.duckduckgo.com/lite/?q={_urlencode(query)}",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urlopen(get_req, timeout=_FETCH_TIMEOUT) as resp:  # noqa: S310
            return resp.read(_MAX_BODY).decode("utf-8", errors="replace"), "lite", None
    except (URLError, OSError, TimeoutError, ValueError) as e:
        return None, "", str(e)


def websearch(query: str, *, max_results: int = 8) -> dict[str, Any]:
    """Search the web via DuckDuckGo (no API key)."""
    query = query.strip()
    if not query:
        return {"ok": False, "error": "query required", "output": "query required"}

    max_results = max(1, min(int(max_results), 15))
    instant_hits = _ddg_instant(query)
    body, source, err = _ddg_html_search(query)
    if err and not instant_hits:
        return {"ok": False, "error": err, "output": err, "engine": "duckduckgo"}

    html_hits = _parse_ddg_html(body or "", max_results) if body else []
    safe_instant = [hit for hit in instant_hits if not hit.get("url") or _url_allowed(hit["url"])]
    safe_html = [hit for hit in html_hits if not hit.get("url") or _url_allowed(hit["url"])]
    results = _merge_search_results(safe_instant, safe_html, max_results=max_results)

    if not results:
        hint = (
            "No results found. Try rephrasing the query, adding more specific keywords, "
            "or fetch a known URL directly with webfetch."
        )
        return {
            "ok": True,
            "output": f"query: {query}\nresults: 0\n\n{hint}",
            "results": [],
            "count": 0,
            "engine": "duckduckgo",
            "query": query,
            "source": source or "instant",
        }

    lines: list[str] = [f"query: {query}", f"results: {len(results)}"]
    if source:
        lines.append(f"source: {source}")
    lines.append("")
    for i, hit in enumerate(results, 1):
        lines.append(f"{i}. {hit.get('title') or '(no title)'}")
        if hit.get("url"):
            lines.append(f"   {hit['url']}")
        if hit.get("snippet"):
            lines.append(f"   {hit['snippet']}")
        lines.append("")

    output = "\n".join(lines).strip()
    return {
        "ok": True,
        "output": output,
        "results": results,
        "count": len(results),
        "engine": "duckduckgo",
        "query": query,
        "source": source or ("instant" if instant_hits and not html_hits else "mixed"),
    }


def webcrawl(
    url: str,
    *,
    max_pages: int = 5,
    max_depth: int = 1,
    same_origin: bool = True,
) -> dict[str, Any]:
    """Crawl starting URL — fetch pages and extract text + links (free, stdlib)."""
    start = unwrap_tracking_url(url.strip())
    blocked = _url_blocked(start)
    if blocked:
        return {"ok": False, "error": blocked, "output": blocked}

    max_pages = max(1, min(int(max_pages), 12))
    max_depth = max(0, min(int(max_depth), 3))
    origin = urlparse(start)
    origin_key = f"{origin.scheme}://{origin.netloc}"

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start, 0)]
    pages: list[dict[str, Any]] = []
    t0 = time.monotonic()
    total_bytes = 0
    budget_exceeded = False

    while queue and len(pages) < max_pages:
        if time.monotonic() - t0 > _CRAWL_MAX_SECONDS:
            budget_exceeded = True
            break
        current, depth = queue.pop(0)
        key = urlparse(current)._replace(fragment="").geturl()
        if key in visited:
            continue
        if not _url_allowed(current):
            pages.append({"url": current, "error": "private network URLs blocked", "depth": depth})
            continue
        visited.add(key)

        raw, ctype, final_url, fetch_err = _fetch_url(current)
        if fetch_err:
            pages.append({"url": current, "error": fetch_err, "depth": depth})
            continue
        total_bytes += len(raw)
        if total_bytes > _CRAWL_MAX_TOTAL_BYTES:
            budget_exceeded = True
            break

        body = _decode_body(raw, ctype)
        title, _description, text, links = _extract_page(body, final_url)
        excerpt = text[:2_500] + ("…" if len(text) > 2_500 else "")
        pages.append(
            {
                "url": final_url,
                "title": title,
                "depth": depth,
                "chars": len(text),
                "excerpt": excerpt,
                "links_found": len(links),
            }
        )

        if depth >= max_depth:
            continue
        for link in links:
            if len(pages) + len(queue) >= max_pages * 3:
                break
            if same_origin and not link.startswith(origin_key):
                continue
            lk = urlparse(link)._replace(fragment="").geturl()
            if lk not in visited and _url_allowed(lk):
                queue.append((lk, depth + 1))

    elapsed = time.monotonic() - t0
    lines = [f"seed: {start}", f"pages: {len(pages)}  depth≤{max_depth}  {elapsed:.1f}s"]
    if budget_exceeded:
        lines.append("budget: time or download limit reached")
    lines.append("")
    for i, p in enumerate(pages, 1):
        if p.get("error"):
            lines.append(f"{i}. [error] {p['url']} — {p['error']}")
            continue
        lines.append(f"{i}. {p.get('title') or '(untitled)'}")
        lines.append(f"   {p['url']}  ({p.get('chars', 0)} chars)")
        if p.get("excerpt"):
            lines.append(f"   {p['excerpt'][:600]}")
        lines.append("")

    return {
        "ok": True,
        "output": "\n".join(lines).strip(),
        "pages": pages,
        "count": len(pages),
        "elapsed_s": round(elapsed, 2),
        "seed": start,
    }
