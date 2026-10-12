from __future__ import annotations

import re

_MARKER_RE = re.compile(r"<!--\s*/?\s*kite:untrusted\b.*?-->", re.IGNORECASE)


def wrap_untrusted_context(
    content: str,
    *,
    source: str,
    guidance: str,
    trust: str = "untrusted",
) -> str:
    """Wrap data as non-authoritative prompt context and neutralize forged markers."""
    body = (content or "").strip()
    if not body:
        return ""
    body = _MARKER_RE.sub(
        lambda match: match.group(0).replace("<", "&lt;").replace(">", "&gt;"),
        body,
    )
    return (
        f"<!-- kite:untrusted source={source} trust={trust} -->\n"
        f"{guidance.strip()}\n\n"
        f"{body}\n"
        "<!-- /kite:untrusted -->"
    )
