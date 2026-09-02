"""Built-in Context7 integration — the only bundled MCP-style docs provider.

HTTP client for Context7's public API (resolve library + query docs).
Optional CONTEXT7_API_KEY in ~/.kite/.env for higher rate limits.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from kite.tools import Tool
from kite.tools.metadata import _meta

_API_BASE = "https://context7.com/api"
_USER_AGENT = "kite-agent/0.8 (+https://github.com/kite-cli)"
_MAX_OUTPUT = 12_000


def _api_key() -> str | None:
    from kite.providers.credentials import context7_api_key

    return context7_api_key()


def _request(path: str, params: dict[str, str], *, api_key: str | None) -> tuple[int, dict[str, Any] | str]:
    query = urlencode({k: v for k, v in params.items() if v})
    url = f"{_API_BASE}{path}?{query}" if query else f"{_API_BASE}{path}"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=25) as resp:  # noqa: S310
            body = resp.read(500_000).decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200) or 200
    except HTTPError as e:
        status = e.code
        try:
            body = e.read().decode("utf-8", errors="replace")
        except OSError:
            body = str(e)
    except (URLError, OSError, TimeoutError, ValueError) as e:
        return 0, str(e)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return status, body
    return status, parsed


def resolve_library(library_name: str, query: str) -> dict[str, Any]:
    """Search Context7 libraries (MCP resolve-library-id equivalent)."""
    library_name = library_name.strip()
    query = query.strip()
    if not library_name or not query:
        return {"ok": False, "error": "library_name and query required", "output": "library_name and query required"}
    status, data = _request(
        "/v2/libs/search",
        {"libraryName": library_name, "query": query},
        api_key=_api_key(),
    )
    if isinstance(data, str):
        return {"ok": False, "error": data, "output": data}
    if status == 401:
        hint = " Set CONTEXT7_API_KEY in ~/.kite/.env (optional; higher limits)."
        return {"ok": False, "error": f"Context7 auth failed.{hint}", "output": f"Context7 auth failed.{hint}"}
    if status >= 400:
        msg = str((data or {}).get("message") or (data or {}).get("error") or f"HTTP {status}")
        return {"ok": False, "error": msg, "output": msg}
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        return {"ok": True, "output": "No libraries matched. Try a different name or websearch.", "results": []}
    lines = ["Context7 library matches (use libraryId with context7_docs):"]
    for row in results[:8]:
        if not isinstance(row, dict):
            continue
        lib_id = str(row.get("id") or "")
        title = str(row.get("title") or row.get("name") or lib_id)
        desc = str(row.get("description") or "").strip()
        line = f"- {lib_id}  {title}"
        if desc:
            line += f"  — {desc[:120]}"
        lines.append(line)
    text = "\n".join(lines)
    top = results[0] if isinstance(results[0], dict) else {}
    return {
        "ok": True,
        "output": text,
        "library_id": str(top.get("id") or ""),
        "results": results[:8],
    }


def query_docs(library_id: str, query: str) -> dict[str, Any]:
    """Fetch Context7 documentation snippets (MCP query-docs equivalent)."""
    library_id = library_id.strip()
    query = query.strip()
    if not library_id or not query:
        return {"ok": False, "error": "library_id and query required", "output": "library_id and query required"}
    if not library_id.startswith("/"):
        library_id = f"/{library_id.lstrip('/')}"
    status, data = _request(
        "/v2/context",
        {"libraryId": library_id, "query": query, "type": "json"},
        api_key=_api_key(),
    )
    if isinstance(data, str):
        return {"ok": False, "error": data, "output": data}
    if status == 301 and isinstance(data, dict) and data.get("redirectUrl"):
        library_id = str(data["redirectUrl"]).strip() or library_id
        status, data = _request(
            "/v2/context",
            {"libraryId": library_id, "query": query, "type": "json"},
            api_key=_api_key(),
        )
        if isinstance(data, str):
            return {"ok": False, "error": data, "output": data}
    if status == 401:
        hint = " Set CONTEXT7_API_KEY in ~/.kite/.env (optional; higher limits)."
        return {"ok": False, "error": f"Context7 auth failed.{hint}", "output": f"Context7 auth failed.{hint}"}
    if status >= 400:
        msg = str((data or {}).get("message") or (data or {}).get("error") or f"HTTP {status}")
        return {"ok": False, "error": msg, "output": msg}
    text = _format_context_payload(data)
    return {"ok": True, "output": text, "library_id": library_id}


def _format_context_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data)[:_MAX_OUTPUT]
    parts: list[str] = []
    for snippet in data.get("codeSnippets") or []:
        if not isinstance(snippet, dict):
            continue
        title = str(snippet.get("codeTitle") or "code").strip()
        parts.append(f"### {title}")
        for block in snippet.get("codeList") or []:
            if not isinstance(block, dict):
                continue
            code = str(block.get("code") or "").strip()
            if code:
                parts.append(f"```\n{code}\n```")
    for snippet in data.get("infoSnippets") or []:
        if not isinstance(snippet, dict):
            continue
        content = str(snippet.get("content") or "").strip()
        if content:
            parts.append(content)
    if not parts:
        # Fallback: compact JSON preview
        preview = json.dumps(data, ensure_ascii=False)[:4000]
        return preview
    text = "\n\n".join(parts)
    if len(text) > _MAX_OUTPUT:
        return text[: _MAX_OUTPUT - 20] + "\n…[truncated]"
    return text


def make_context7_tools(*, enabled: bool = True) -> list[Tool]:
    if not enabled:
        return []
    net = _meta(read_only=True, network=True, expensive=True)

    def _resolve(args: dict[str, Any]) -> dict[str, Any]:
        return resolve_library(str(args.get("library_name") or ""), str(args.get("query") or ""))

    def _docs(args: dict[str, Any]) -> dict[str, Any]:
        return query_docs(str(args.get("library_id") or ""), str(args.get("query") or ""))

    return [
        Tool(
            "context7_resolve",
            (
                "Built-in Context7 (only bundled docs MCP): resolve a library name to a "
                "Context7 libraryId. Call before context7_docs unless the user gave /org/project."
            ),
            {
                "type": "object",
                "properties": {
                    "library_name": {
                        "type": "string",
                        "description": "Library or framework name (e.g. react, next.js, pydantic)",
                    },
                    "query": {
                        "type": "string",
                        "description": "What you need help with — used to rank matches",
                    },
                },
                "required": ["library_name", "query"],
            },
            _resolve,
            metadata=net,
        ),
        Tool(
            "context7_docs",
            (
                "Built-in Context7: fetch up-to-date docs and examples for a libraryId "
                "(from context7_resolve or /org/project). Prefer over guessing API details."
            ),
            {
                "type": "object",
                "properties": {
                    "library_id": {
                        "type": "string",
                        "description": "Context7 library ID, e.g. /vercel/next.js",
                    },
                    "query": {
                        "type": "string",
                        "description": "Specific question or task",
                    },
                },
                "required": ["library_id", "query"],
            },
            _docs,
            metadata=net,
        ),
    ]
