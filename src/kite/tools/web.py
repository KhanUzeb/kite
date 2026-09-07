"""Free web search and fetch — no API keys required (stdlib urllib).

websearch: DuckDuckGo HTML results.
webfetch:  fetch one URL and return extracted readable text (not raw HTML soup).
webcrawl:  same-origin crawl with depth/page limits.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener, urlopen

try:
    from kite import __version__
except Exception:  # pragma: no cover
    __version__ = "0.9.1"

_USER_AGENT = f"kite-agent/{__version__} (+https://github.com/KhanUzeb/kite)"
_MAX_BODY = 120_000
_FETCH_TIMEOUT = 20
_DEFAULT_FETCH_CHARS = 24_000
_MAX_REDIRECTS = 5
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "0.0.0.0",
        "metadata.google.internal",
        "metadata.google",
    }
)
_BLOCKED_IPS = frozenset(
    {
        "169.254.169.254",
        "100.100.100.200",
        "127.0.0.1",
        "0.0.0.0",
    }
)


def _parse_host_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    token = (host or "").strip().lower().rstrip(".")
    if not token:
        return None
    if token in _BLOCKED_HOSTS:
        return ipaddress.ip_address("127.0.0.1")
    if token.isdigit():
        try:
            return ipaddress.IPv4Address(int(token))
        except ValueError:
            return None
    if token.startswith("0x"):
        try:
            return ipaddress.IPv4Address(int(token, 16))
        except ValueError:
            return None
    if token.startswith("0") and len(token) > 1 and token[1:].isdigit():
        try:
            return ipaddress.IPv4Address(int(token, 8))
        except ValueError:
            pass
    try:
        return ipaddress.ip_address(token)
    except ValueError:
        pass
    if token.startswith("[") and token.endswith("]"):
        try:
            return ipaddress.ip_address(token[1:-1])
        except ValueError:
            return None
    return None


def _ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if str(ip) in _BLOCKED_IPS:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        err = _url_blocked(newurl)
        if err:
            raise URLError(err)
        old = urlparse(req.full_url)
        new = urlparse(newurl)
        if new.scheme not in {"http", "https"}:
            raise URLError("redirect to non-http(s) scheme blocked")
        if old.scheme == "https" and new.scheme == "http":
            raise URLError("https→http downgrade redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_opener() -> OpenerDirector:
    return build_opener(_SafeRedirectHandler())


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    literal = _parse_host_ip(host)
    if literal is not None:
        return [literal]
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        key = str(ip)
        if key not in seen:
            seen.add(key)
            ips.append(ip)
    return ips


def _url_blocked(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return "only http(s) URLs allowed"
    host = (parsed.hostname or "").lower()
    if not host:
        return "invalid URL"
    if host in _BLOCKED_HOSTS or host.endswith(".local"):
        return "local URLs blocked"
    literal = _parse_host_ip(host)
    if literal is not None and _ip_blocked(literal):
        return "private network URLs blocked"
    for ip in _resolve_host_ips(host):
        if _ip_blocked(ip):
            return "private network URLs blocked"
    return None


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
            return unquote(target)
    if host.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q", [None])[0]
        if target:
            return unquote(target)
    return text


def _fetch_url(
    url: str,
    *,
    timeout: int = _FETCH_TIMEOUT,
    max_bytes: int = _MAX_BODY,
) -> tuple[bytes, str, str | None]:
    """Return (raw_bytes, content_type, error)."""
    err = _url_blocked(url)
    if err:
        return b"", "", err
    req = Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with _safe_opener().open(req, timeout=timeout) as resp:  # noqa: S310
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return resp.read(max_bytes), ctype, None
    except (URLError, OSError, TimeoutError, ValueError) as e:
        return b"", "", str(e)


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
        self._skip_tags = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_tags += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "code", "article", "main", "td", "th"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_tags:
            self._skip_tags -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_tags:
            return
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
    return title, text, links


def _decode_body(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].strip() or charset
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


def webfetch(
    url: str,
    *,
    timeout: int = _FETCH_TIMEOUT,
    max_chars: int = _DEFAULT_FETCH_CHARS,
    extract: bool = True,
) -> dict[str, Any]:
    """Fetch one URL and return readable text (HTML stripped by default)."""
    target = unwrap_tracking_url(url.strip())
    err = _url_blocked(target)
    if err:
        return {"ok": False, "error": err, "output": err, "url": target}

    raw, content_type, fetch_err = _fetch_url(target, timeout=max(1, int(timeout)))
    if fetch_err:
        return {"ok": False, "error": fetch_err, "output": fetch_err, "url": target}

    max_chars = max(500, min(int(max_chars), 80_000))
    title = ""
    truncated = False

    if content_type.startswith("application/json") or target.endswith(".json"):
        text = _format_json_text(raw, max_chars=max_chars)
    elif extract and ("html" in content_type or "<html" in raw[:500].lower()):
        body = _decode_body(raw, content_type)
        title, text, _links = _extract_page(body, target)
        text, truncated = _truncate_middle(text, max_chars)
    else:
        text = _decode_body(raw, content_type)
        text, truncated = _truncate_middle(text, max_chars)

    lines = [
        f"url: {target}",
        f"content-type: {content_type or 'unknown'}",
        f"chars: {len(text)}",
    ]
    if title:
        lines.append(f"title: {title}")
    if truncated:
        lines.append("truncated: true")
    lines.extend(["", text])
    output = "\n".join(lines).strip()

    return {
        "ok": True,
        "output": output,
        "url": target,
        "title": title,
        "content_type": content_type,
        "truncated": truncated,
        "chars": len(text),
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


def _parse_ddg_html(body: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML result blocks."""
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
        key = urlparse(url)._replace(fragment="").geturl()
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
            key = urlparse(hit["url"])._replace(fragment="").geturl()
            if key in seen:
                continue
            seen.add(key)
            results.append(hit)
            if len(results) >= max_results:
                break
    return results[:max_results]


def _ddg_instant(query: str) -> dict[str, str] | None:
    url = f"https://api.duckduckgo.com/?q={_urlencode(query)}&format=json&no_html=1&skip_disambig=1"
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read(32_000).decode("utf-8", errors="replace"))
    except Exception:
        return None
    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = unwrap_tracking_url((data.get("AbstractURL") or "").strip())
    heading = (data.get("Heading") or query).strip()
    if abstract:
        return {"title": heading, "url": abstract_url, "snippet": abstract}
    related = data.get("RelatedTopics") or []
    for item in related:
        if isinstance(item, dict) and item.get("Text"):
            return {
                "title": heading,
                "url": unwrap_tracking_url(str(item.get("FirstURL") or "")),
                "snippet": str(item["Text"])[:400],
            }
    return None


def _ddg_html_search(query: str) -> tuple[str | None, str | None]:
    """Return (html_body, error). Tries POST html endpoint, then GET lite."""
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
            return resp.read(_MAX_BODY).decode("utf-8", errors="replace"), None
    except (URLError, OSError, TimeoutError, ValueError):
        pass

    get_req = Request(
        f"https://lite.duckduckgo.com/lite/?q={_urlencode(query)}",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urlopen(get_req, timeout=_FETCH_TIMEOUT) as resp:  # noqa: S310
            return resp.read(_MAX_BODY).decode("utf-8", errors="replace"), None
    except (URLError, OSError, TimeoutError, ValueError) as e:
        return None, str(e)


def websearch(query: str, *, max_results: int = 8) -> dict[str, Any]:
    """Search the web via DuckDuckGo HTML (no API key)."""
    query = query.strip()
    if not query:
        return {"ok": False, "error": "query required", "output": "query required"}

    max_results = max(1, min(int(max_results), 15))
    body, err = _ddg_html_search(query)
    if err:
        return {"ok": False, "error": err, "output": err, "engine": "duckduckgo"}

    results = _parse_ddg_html(body or "", max_results)
    if not results:
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

    while queue and len(pages) < max_pages:
        current, depth = queue.pop(0)
        key = urlparse(current)._replace(fragment="").geturl()
        if key in visited:
            continue
        visited.add(key)

        raw, ctype, fetch_err = _fetch_url(current)
        if fetch_err:
            pages.append({"url": current, "error": fetch_err, "depth": depth})
            continue

        body = _decode_body(raw, ctype)
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
