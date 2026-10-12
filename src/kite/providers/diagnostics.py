from __future__ import annotations

import re

from kite.guardrails.redact import redact_string

_HTTP_STATUS_RE = re.compile(r"\b(?:HTTP\s*)?(\d{3})\b", re.IGNORECASE)


def format_provider_failure(message: str, *, provider: str = "") -> str:
    """Return redacted provider failure detail with category-specific next action."""
    safe = " ".join(redact_string(str(message or "")).split())[:300]
    lowered = safe.lower()
    provider_name = (provider or "").strip().lower()
    status_codes = {int(match.group(1)) for match in _HTTP_STATUS_RE.finditer(safe)}

    if any(marker in lowered for marker in ("quota", "billing limit", "usage limit")):
        category = "provider quota reached"
        action = "check the provider's subscription or quota reset"
    elif any(
        marker in lowered
        for marker in ("unauthorized", "authentication failed", "invalid api key", "not linked", "expired credential")
    ):
        category = "provider authentication failed"
        action = (
            f"run `kite login {provider_name}` to relink"
            if provider_name == "antigravity"
            else "check credentials with `kite keys` and relink with `kite login`"
        )
    elif any(marker in lowered for marker in ("rate limit", "too many requests")) or 429 in status_codes:
        category = "provider rate limit"
        action = "wait briefly, then retry"
    elif any(marker in lowered for marker in ("timeout", "timed out", "connection", "network", "unreachable")):
        category = "provider connection failure"
        action = "check the network and provider availability, then retry"
    elif any(500 <= code <= 599 for code in status_codes) or any(
        marker in lowered for marker in ("service unavailable", "upstream error", "server error", "overloaded")
    ):
        category = "provider service failure"
        action = "check provider status and retry when the service recovers"
    else:
        category = "provider request failed"
        action = "check provider configuration and the error detail"

    detail = f": {safe}" if safe else ""
    return f"{category}{detail}. Next: {action}."
