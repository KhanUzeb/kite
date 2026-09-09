"""Infer synchronous vs background dispatch for orchestrated workers."""

from __future__ import annotations

import re
from typing import Any

_ASYNC_PATTERNS = (
    r"\bbackground\b",
    r"\basync(?:hronous)?\b",
    r"\bfire[- ]and[- ]forget\b",
    r"\bwithout waiting\b",
    r"\bdon'?t wait\b",
    r"\bnon[- ]blocking\b",
    r"\bwhile (?:i|we|you) continue\b",
    r"\bspawn and (?:move on|continue)\b",
    r"\bin the background\b",
    r"\bparallel exploration\b.*\bcontinue\b",
)

_SYNC_PATTERNS = (
    r"\bwait for (?:results?|findings?|output)\b",
    r"\breport back\b",
    r"\bsummarize and return\b",
    r"\bintegrate findings\b",
    r"\bbefore (?:continuing|proceeding)\b",
    r"\bblocking\b",
    r"\bneed (?:the )?results?\b",
    r"\bthen continue\b",
    r"\bmerge (?:the )?findings\b",
    r"\breturn (?:a )?summary\b",
)


def _collect_text(args: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("prompt", "label"):
        val = args.get(key)
        if val:
            chunks.append(str(val))
    for key in ("prompts", "tasks", "labels"):
        val = args.get(key)
        if isinstance(val, list):
            chunks.extend(str(x) for x in val)
    return "\n".join(chunks).lower()


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pat, text, re.IGNORECASE) for pat in patterns)


def resolve_dispatch_mode(args: dict[str, Any]) -> tuple[bool, str]:
    """Return (background, reason). Default sync unless auto heuristics prefer async."""
    if args.get("background") is True or args.get("async") is True:
        return True, "explicit-async"
    if args.get("wait") is False:
        return True, "explicit-async"
    if args.get("background") is False or args.get("wait") is True:
        return False, "explicit-sync"

    prompts = args.get("prompts") or args.get("tasks")
    if isinstance(prompts, list) and len(prompts) > 1:
        # Parallel crew merges results — stay synchronous unless caller opts out.
        return False, "parallel-crew-sync"

    text = _collect_text(args)
    if _matches_any(text, _ASYNC_PATTERNS):
        return True, "auto-async"
    if _matches_any(text, _SYNC_PATTERNS):
        return False, "auto-sync"
    return False, "default-sync"
