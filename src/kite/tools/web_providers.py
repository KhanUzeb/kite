"""Optional paid web backends for websearch / webfetch / webcrawl.

Auto search order when keys are set: Tavily → Exa → Firecrawl → DuckDuckGo.
Firecrawl also upgrades webfetch (scrape) and webcrawl when FIRECRAWL_API_KEY is set.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_log = logging.getLogger("kite.tools.web_providers")

_USER_AGENT = "kite-agent/0.9 (+https://github.com/KhanUzeb/kite)"
_TIMEOUT = 45

WEB_TOOL_ENVS: dict[str, str] = {
    "tavily": "TAVILY_API_KEY",
    "exa": "EXA_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
}

SEARCH_AUTO_ORDER = ("tavily", "exa", "firecrawl", "duckduckgo")


def resolve_web_tool_env(name: str) -> str | None:
    return WEB_TOOL_ENVS.get((name or "").strip().lower())


def _env_key(name: str) -> str | None:
    import os

    from kite.providers.credentials import load_kite_env

    load_kite_env()
    env = WEB_TOOL_ENVS.get(name)
    if not env:
        return None
    val = (os.getenv(env) or "").strip()
    return val or None


def tavily_api_key() -> str | None:
    return _env_key("tavily")


def exa_api_key() -> str | None:
    return _env_key("exa")


def firecrawl_api_key() -> str | None:
    return _env_key("firecrawl")


def resolve_search_engines(preference: str = "auto") -> list[str]:
    pref = (preference or "auto").strip().lower()
    if pref in {"tavily", "exa", "firecrawl", "duckduckgo", "ddg"}:
        if pref == "ddg":
            pref = "duckduckgo"
        if pref == "duckduckgo":
            return ["duckduckgo"]
        key_fn = {"tavily": tavily_api_key, "exa": exa_api_key, "firecrawl": firecrawl_api_key}[pref]
        return [pref, "duckduckgo"] if key_fn() else ["duckduckgo"]

    engines: list[str] = []
    if tavily_api_key():
        engines.append("tavily")
    if exa_api_key():
        engines.append("exa")
    if firecrawl_api_key():
        engines.append("firecrawl")
    engines.append("duckduckgo")
    return engines


def _http_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = _TIMEOUT,
    method: str | None = None,
) -> tuple[int, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req_headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if body is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)
    verb = method or ("POST" if body is not None else "GET")
    req = Request(url, data=payload, headers=req_headers, method=verb)
    try:
        with urlopen(req, timeout=max(5, int(timeout))) as resp:  # noqa: S310
            raw = resp.read(2_000_000).decode("utf-8", errors="replace")
            status = int(getattr(resp, "status", 200) or 200)
    except HTTPError as e:
        status = int(e.code)
        try:
            raw = e.read(500_000).decode("utf-8", errors="replace")
        except OSError:
            raw = str(e)
    except (URLError, OSError, TimeoutError, ValueError) as e:
        return 0, str(e)
    try:
        return status, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return status, raw


def _normalize_hits(rows: list[dict[str, Any]], *, max_results: int) -> list[dict[str, str]]:
    from kite.tools.web import _url_allowed, unwrap_tracking_url

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("link") or "").strip()
        if url:
            url = unwrap_tracking_url(url)
            if not _url_allowed(url) or url in seen:
                continue
            seen.add(url)
        title = str(row.get("title") or "").strip()
        snippet = str(
            row.get("snippet")
            or row.get("content")
            or row.get("text")
            or row.get("description")
            or ""
        ).strip()
        if not (title or url or snippet):
            continue
        hit = {"title": title or "(no title)", "url": url, "snippet": snippet[:500]}
        out.append(hit)
        if len(out) >= max_results:
            break
    return out


def _format_search_output(query: str, results: list[dict[str, str]], *, engine: str) -> str:
    lines = [f"query: {query}", f"results: {len(results)}", f"engine: {engine}", ""]
    for i, hit in enumerate(results, 1):
        lines.append(f"{i}. {hit.get('title') or '(no title)'}")
        if hit.get("url"):
            lines.append(f"   {hit['url']}")
        if hit.get("snippet"):
            lines.append(f"   {hit['snippet']}")
        lines.append("")
    return "\n".join(lines).strip()


def search_tavily(query: str, *, max_results: int, api_key: str) -> dict[str, Any] | None:
    status, data = _http_json(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {api_key}"},
        body={"query": query, "max_results": max_results, "include_answer": False},
    )
    if status < 200 or status >= 300 or not isinstance(data, dict):
        _log.debug("tavily search failed status=%s", status)
        return None
    rows = data.get("results") if isinstance(data.get("results"), list) else []
    results = _normalize_hits(
        [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content")} for r in rows if isinstance(r, dict)],
        max_results=max_results,
    )
    if not results:
        return None
    return {
        "ok": True,
        "output": _format_search_output(query, results, engine="tavily"),
        "results": results,
        "count": len(results),
        "engine": "tavily",
        "query": query,
        "source": "api",
    }


def search_exa(query: str, *, max_results: int, api_key: str) -> dict[str, Any] | None:
    status, data = _http_json(
        "https://api.exa.ai/search",
        headers={"Authorization": f"Bearer {api_key}", "x-api-key": api_key},
        body={
            "query": query,
            "numResults": max_results,
            "type": "auto",
            "contents": {"highlights": True},
        },
    )
    if status < 200 or status >= 300 or not isinstance(data, dict):
        _log.debug("exa search failed status=%s", status)
        return None
    rows = data.get("results") if isinstance(data.get("results"), list) else []
    normalized = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        highlights = r.get("highlights")
        snippet = ""
        if isinstance(highlights, list) and highlights:
            snippet = " … ".join(str(h) for h in highlights[:3])
        elif r.get("text"):
            snippet = str(r.get("text"))[:500]
        normalized.append({"title": r.get("title"), "url": r.get("url"), "snippet": snippet})
    results = _normalize_hits(normalized, max_results=max_results)
    if not results:
        return None
    return {
        "ok": True,
        "output": _format_search_output(query, results, engine="exa"),
        "results": results,
        "count": len(results),
        "engine": "exa",
        "query": query,
        "source": "api",
    }


def search_firecrawl(query: str, *, max_results: int, api_key: str) -> dict[str, Any] | None:
    status, data = _http_json(
        "https://api.firecrawl.dev/v1/search",
        headers={"Authorization": f"Bearer {api_key}"},
        body={"query": query, "limit": max_results},
    )
    if status < 200 or status >= 300 or not isinstance(data, dict):
        _log.debug("firecrawl search failed status=%s", status)
        return None
    raw_results = data.get("data") if isinstance(data.get("data"), list) else data.get("results")
    if not isinstance(raw_results, list):
        # v1 sometimes nests under data.web
        nested = data.get("data")
        if isinstance(nested, dict) and isinstance(nested.get("web"), list):
            raw_results = nested["web"]
        else:
            raw_results = []
    normalized = []
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        normalized.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "snippet": r.get("description") or r.get("markdown") or r.get("content"),
            }
        )
    results = _normalize_hits(normalized, max_results=max_results)
    if not results:
        return None
    return {
        "ok": True,
        "output": _format_search_output(query, results, engine="firecrawl"),
        "results": results,
        "count": len(results),
        "engine": "firecrawl",
        "query": query,
        "source": "api",
    }


def paid_websearch(query: str, *, max_results: int, preference: str = "auto") -> dict[str, Any] | None:
    """Try configured paid engines; return None to fall through to DuckDuckGo."""
    for engine in resolve_search_engines(preference):
        if engine == "duckduckgo":
            return None
        if engine == "tavily":
            key = tavily_api_key()
            if key:
                hit = search_tavily(query, max_results=max_results, api_key=key)
                if hit:
                    return hit
        elif engine == "exa":
            key = exa_api_key()
            if key:
                hit = search_exa(query, max_results=max_results, api_key=key)
                if hit:
                    return hit
        elif engine == "firecrawl":
            key = firecrawl_api_key()
            if key:
                hit = search_firecrawl(query, max_results=max_results, api_key=key)
                if hit:
                    return hit
    return None


def firecrawl_scrape(url: str, *, api_key: str, timeout: int = _TIMEOUT) -> dict[str, Any] | None:
    status, data = _http_json(
        "https://api.firecrawl.dev/v1/scrape",
        headers={"Authorization": f"Bearer {api_key}"},
        body={"url": url, "formats": ["markdown", "links"]},
        timeout=timeout,
    )
    if status < 200 or status >= 300 or not isinstance(data, dict):
        _log.debug("firecrawl scrape failed status=%s", status)
        return None
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return None
    markdown = str(payload.get("markdown") or payload.get("content") or "").strip()
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    title = str(meta.get("title") or "").strip()
    description = str(meta.get("description") or "").strip()
    final_url = str(meta.get("sourceURL") or meta.get("url") or url).strip()
    links = payload.get("links") if isinstance(payload.get("links"), list) else []
    if not markdown:
        return None
    lines = [
        f"url: {final_url}",
        "engine: firecrawl",
        f"chars: {len(markdown)}",
    ]
    if title:
        lines.append(f"title: {title}")
    if description:
        lines.append(f"description: {description}")
    lines.extend(["", markdown])
    return {
        "ok": True,
        "output": "\n".join(lines).strip(),
        "url": final_url,
        "requested_url": url,
        "title": title,
        "description": description,
        "content_type": "text/markdown",
        "truncated": False,
        "chars": len(markdown),
        "links": [str(x) for x in links[:12]],
        "engine": "firecrawl",
    }


def firecrawl_crawl(
    url: str,
    *,
    api_key: str,
    max_pages: int = 5,
    timeout: int = 90,
) -> dict[str, Any] | None:
    status, data = _http_json(
        "https://api.firecrawl.dev/v1/crawl",
        headers={"Authorization": f"Bearer {api_key}"},
        body={"url": url, "limit": max_pages},
        timeout=30,
    )
    if status < 200 or status >= 300 or not isinstance(data, dict):
        _log.debug("firecrawl crawl start failed status=%s", status)
        return None
    job_id = str(data.get("id") or data.get("jobId") or "").strip()
    if not job_id:
        # Some responses return data inline
        pages = data.get("data")
        if isinstance(pages, list) and pages:
            return _format_crawl_pages(url, pages, max_pages=max_pages)
        return None

    deadline = time.monotonic() + max(15, int(timeout))
    while time.monotonic() < deadline:
        st, body = _http_json(
            f"https://api.firecrawl.dev/v1/crawl/{job_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        if st < 200 or st >= 300 or not isinstance(body, dict):
            time.sleep(1.5)
            continue
        state = str(body.get("status") or "").lower()
        if state in {"completed", "done", "success"}:
            pages = body.get("data")
            if isinstance(pages, list):
                return _format_crawl_pages(url, pages, max_pages=max_pages)
            return None
        if state in {"failed", "error", "cancelled"}:
            return None
        time.sleep(1.5)
    return None


def _format_crawl_pages(seed: str, pages: list[Any], *, max_pages: int) -> dict[str, Any]:
    lines = [f"seed: {seed}", "engine: firecrawl", f"pages: {min(len(pages), max_pages)}", ""]
    kept = 0
    for page in pages:
        if kept >= max_pages:
            break
        if not isinstance(page, dict):
            continue
        meta = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
        title = str(meta.get("title") or "").strip() or "(untitled)"
        src = str(meta.get("sourceURL") or meta.get("url") or "").strip()
        md = str(page.get("markdown") or page.get("content") or "").strip()
        lines.append(f"{kept + 1}. {title}")
        if src:
            lines.append(f"   {src}")
        if md:
            lines.append(f"   {md[:400]}")
        lines.append("")
        kept += 1
    if kept == 0:
        return {"ok": False, "error": "firecrawl crawl returned no pages", "output": "firecrawl crawl returned no pages"}
    return {
        "ok": True,
        "output": "\n".join(lines).strip(),
        "engine": "firecrawl",
        "pages": kept,
        "seed": seed,
    }
