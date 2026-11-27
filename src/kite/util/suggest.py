"""Small did-you-mean helper for CLI and slash-command errors."""

from __future__ import annotations

import difflib
import re

_SEPARATORS = re.compile(r"[-_/.\s]+")


def normalize(name: str) -> str:
    """Fold naming styles so `set_provider` and `set-provider` compare equal."""
    return _SEPARATORS.sub("", (name or "").strip().lower().lstrip("/"))


def closest(name: str, candidates, *, limit: int = 1, cutoff: float = 0.62) -> list[str]:
    """Return up to `limit` close candidate spellings, as supplied.

    The exact spelling is excluded: a suggestion must tell the user something
    they did not already type.
    """
    needle = (name or "").strip().lower().lstrip("/")
    if not needle:
        return []
    pool: dict[str, str] = {}
    for item in candidates:
        candidate = str(item).strip()
        key = candidate.lstrip("/").lower()
        if not key or key == needle:
            continue
        pool.setdefault(key, candidate)
    if not pool:
        return []
    direct = difflib.get_close_matches(needle, list(pool), n=limit, cutoff=cutoff)
    if direct:
        return [pool[key] for key in direct]
    folded = {normalize(key): value for key, value in pool.items()}
    matches = difflib.get_close_matches(normalize(needle), list(folded), n=limit, cutoff=cutoff)
    return [folded[key] for key in matches]


def did_you_mean(name: str, candidates, *, limit: int = 1) -> str:
    """Ready-to-append error suffix, or "" when nothing is close enough."""
    hits = closest(name, candidates, limit=limit)
    if not hits:
        return ""
    return "did you mean " + " or ".join(f"'{hit}'" for hit in hits) + "?"
