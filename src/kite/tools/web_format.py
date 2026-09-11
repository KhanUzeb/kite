"""Token-efficient formatting for websearch / webfetch output."""

from __future__ import annotations

from typing import Any


def _clamp_snippet(snippet: str, max_chars: int) -> str:
    text = (snippet or "").strip().replace("\n", " ")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def format_search_output(
    query: str,
    results: list[dict[str, str]],
    *,
    engine: str,
    source: str = "",
    urls_only: bool = False,
    compact: bool = False,
    max_snippet_chars: int = 220,
) -> str:
    lines = [f"query: {query}", f"results: {len(results)}", f"engine: {engine}"]
    if source:
        lines.append(f"source: {source}")
    lines.append("")

    for i, hit in enumerate(results, 1):
        title = (hit.get("title") or "(no title)").strip()
        url = (hit.get("url") or "").strip()
        snippet = _clamp_snippet(str(hit.get("snippet") or ""), max_snippet_chars)
        if urls_only:
            if url:
                lines.append(f"{i}. {url}")
            continue
        if compact:
            line = f"{i}. {title}"
            if url:
                line += f"  {url}"
            lines.append(line)
            continue
        lines.append(f"{i}. {title}")
        if url:
            lines.append(f"   {url}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines).strip()


def search_summary(results: list[dict[str, str]], *, engine: str) -> str:
    return f"{len(results)} result(s) via {engine}"


def slice_body_text(
    text: str,
    *,
    start: int = 0,
    max_chars: int | None = None,
    max_lines: int | None = None,
) -> tuple[str, bool]:
    """Return (slice, truncated)."""
    body = text or ""
    if start > 0:
        body = body[start:]
    truncated = False
    if max_lines is not None and max_lines > 0:
        lines = body.splitlines()
        if len(lines) > max_lines:
            body = "\n".join(lines[:max_lines])
            truncated = True
    if max_chars is not None and max_chars > 0 and len(body) > max_chars:
        head = int(max_chars * 0.7)
        tail = max(0, max_chars - head - 20)
        body = body[:head] + "\n…[truncated]…\n" + body[-tail:]
        truncated = True
    return body, truncated


def format_fetch_output(
    *,
    final_url: str,
    requested_url: str,
    content_type: str,
    title: str,
    description: str,
    text: str,
    engine: str = "stdlib",
    preview_only: bool = False,
    include_links: bool = False,
    outbound_links: list[str] | None = None,
    max_links: int = 12,
    truncated: bool = False,
) -> tuple[str, str]:
    """Return (output, summary)."""
    lines = [f"url: {final_url}"]
    if final_url != requested_url:
        lines.append(f"requested: {requested_url}")
    lines.append(f"engine: {engine}")
    lines.append(f"content-type: {content_type or 'unknown'}")
    if title:
        lines.append(f"title: {title}")
    if description:
        lines.append(f"description: {description}")
    if preview_only:
        lines.append("preview_only: true")
        summary = title or final_url
        return "\n".join(lines).strip(), summary

    lines.append(f"chars: {len(text)}")
    if truncated:
        lines.append("truncated: true")
    links = outbound_links or []
    if include_links and links:
        lines.append(f"links: {len(links)}")
        for link in links[:max_links]:
            lines.append(f"  - {link}")
        if len(links) > max_links:
            lines.append(f"  … and {len(links) - max_links} more")
    lines.extend(["", text])
    summary = title or (text[:80].replace("\n", " ") + ("…" if len(text) > 80 else ""))
    return "\n".join(lines).strip(), summary


__all__ = [
    "format_fetch_output",
    "format_search_output",
    "search_summary",
    "slice_body_text",
]
