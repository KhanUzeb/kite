"""Free web search and crawl — no API keys required.

websearch: DuckDuckGo HTML (lite) results via stdlib urllib.
webcrawl:  fetch a page and follow same-origin links up to a depth/limit.
"""

from __future__ import annotations

import html
import re
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

_USER_AGENT = "kite-agent/0.4 (+https://github.com/kite-cli)"
_MAX_BODY = 120_000
_FETCH_TIMEOUT = 20


def _fetch_url(url: str, *, timeout: int = _FETCH_TIMEOUT, max_bytes: int = _MAX_BODY) -> tuple[str, str | None]:
    """Return (text, error)."""
    if not url.startswith(("http://", "https://")):
        return "", "only http(s) URLs allowed"
    req = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read(max_bytes)
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), None
    except (URLError, OSError, TimeoutError, ValueError) as e:
        return "", str(e)


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.title = ""
        self._in_title = False
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "pre", "code", "article"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        else:
            self.text_parts.append(data)


def _extract_page(body: str, base_url: str) -> tuple[str, str, list[str]]:
    """Return (title, text, absolute_links)."""
    parser = _LinkExtractor()
    try:
        parser.feed(body)
    except Exception:
        pass
    title = _normalize_ws(parser.title)
    text = _normalize_ws("".join(parser.text_parts))
    if not text:
        text = _normalize_ws(_strip_tags(body))
    base = urlparse(base_url)
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        key = parsed._replace(fragment="").geturl()
        if key not in seen:
            seen.add(key)
            links.append(key)
    return title, text, links


def websearch(query: str, *, max_results: int = 8) -> dict[str, Any]:
    """Search the web via DuckDuckGo HTML (no API key)."""
    query = query.strip()
    if not query:
        return {"ok": False, "error": "query required", "output": "query required"}
    max_results = max(1, min(int(max_results), 15))

    # DuckDuckGo lite HTML endpoint — free, no key.
    data = f"q={_urlencode(query)}".encode()
    req = Request(
        "https://html.duckduckgo.com/html/",
        data=data,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=_FETCH_TIMEOUT) as resp:  # noqa: S310
            body = resp.read(_MAX_BODY).decode("utf-8", errors="replace")
    except (URLError, OSError, TimeoutError, ValueError) as e:
        return {"ok": False, "error": str(e), "output": str(e), "engine": "duckduckgo"}

    results = _parse_ddg_html(body, max_results)
    if not results:
        # Fallback: DuckDuckGo instant answer API (limited but sometimes useful).
        instant = _ddg_instant(query)
        if instant:
            results = [instant]

    lines: list[str] = [f"query: {query}", f"results: {len(results)}", ""]
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
    }


def _urlencode(text: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(text)


def _parse_ddg_html(body: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML result blocks."""
    results: list[dict[str, str]] = []
    # Result blocks: <a class="result__a" href="...">title</a> ... <a class="result__snippet">
    for block in re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
        body,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        url_raw, title_raw, snippet_raw = block
        url = _normalize_ws(_strip_tags(url_raw))
        if url.startswith("//"):
            url = "https:" + url
        title = _normalize_ws(_strip_tags(title_raw))
        snippet = _normalize_ws(_strip_tags(snippet_raw))
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _ddg_instant(query: str) -> dict[str, str] | None:
    url = f"https://api.duckduckgo.com/?q={_urlencode(query)}&format=json&no_html=1&skip_disambig=1"
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            import json

            data = json.loads(resp.read(32_000).decode("utf-8", errors="replace"))
    except Exception:
        return None
    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = (data.get("AbstractURL") or "").strip()
    heading = (data.get("Heading") or query).strip()
    if abstract:
        return {"title": heading, "url": abstract_url, "snippet": abstract}
    related = data.get("RelatedTopics") or []
    for item in related:
        if isinstance(item, dict) and item.get("Text"):
            return {
                "title": heading,
                "url": item.get("FirstURL") or "",
                "snippet": str(item["Text"])[:400],
            }
    return None


def webcrawl(
    url: str,
    *,
    max_pages: int = 5,
    max_depth: int = 1,
    same_origin: bool = True,
) -> dict[str, Any]:
    """Crawl starting URL — fetch pages and extract text + links (free, stdlib)."""
    start = url.strip()
    if not start.startswith(("http://", "https://")):
        return {"ok": False, "error": "only http(s) URLs allowed", "output": "only http(s) URLs allowed"}

    max_pages = max(1, min(int(max_pages), 12))
    max_depth = max(0, min(int(max_depth), 3))
    origin = urlparse(start)
    origin_key = f"{origin.scheme}://{origin.netloc}"

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start, 0)]
    pages: list[dict[str, Any]] = []
    t0 = time.monotonic()

    while queue and len(pages) < max_pages:
        current, depth = queue.pop(0)
        key = urlparse(current)._replace(fragment="").geturl()
        if key in visited:
            continue
        visited.add(key)

        body, err = _fetch_url(current)
        if err:
            pages.append({"url": current, "error": err, "depth": depth})
            continue

        title, text, links = _extract_page(body, current)
        excerpt = text[:2_500] + ("…" if len(text) > 2_500 else "")
        pages.append(
            {
                "url": current,
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
            if lk not in visited:
                queue.append((lk, depth + 1))

    elapsed = time.monotonic() - t0
    lines = [f"seed: {start}", f"pages: {len(pages)}  depth≤{max_depth}  {elapsed:.1f}s", ""]
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
