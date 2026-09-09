"""Recursive secret sanitization for audit, sessions, and events."""

from __future__ import annotations

import re
from typing import Any

from kite.guardrails import redact_secrets

REDACTED = "[REDACTED]"
REDACTED_SECRET = "[REDACTED_SECRET]"

# Key names whose values are always redacted regardless of content shape.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)^(.*\.)?(api[_-]?key|secret|token|password|passwd|authorization|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|cookie|set[_-]?cookie|"
    r"pkce|code_verifier|auth_code|authorization_code|bearer|credential)s?$"
)

# Header / cookie patterns inside strings.
_AUTH_HEADER_RE = re.compile(r"(?i)(Authorization\s*:\s*)(Bearer\s+)?\S+")
_COOKIE_RE = re.compile(r"(?i)(Set-Cookie\s*:\s*)\S+")
_PKCE_RE = re.compile(r"(?i)(code_verifier\s*[:=]\s*)\S+")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")


def redact_string(text: str) -> str:
    if not text:
        return text
    out, _ = redact_secrets(text)
    out = _AUTH_HEADER_RE.sub(r"\1Bearer " + REDACTED, out)
    out = _COOKIE_RE.sub(r"\1" + REDACTED, out)
    out = _PKCE_RE.sub(r"\1" + REDACTED, out)
    out = _BEARER_RE.sub("Bearer " + REDACTED, out)
    return out.replace(REDACTED_SECRET, REDACTED)


def _key_sensitive(key: Any) -> bool:
    return isinstance(key, str) and bool(_SENSITIVE_KEY_RE.match(key.strip()))


def sanitize_value(value: Any) -> Any:
    """Recursively redact secrets in nested structures (str, dict, list, tuple, set)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, bytes):
        try:
            return redact_string(value.decode("utf-8", errors="replace"))
        except Exception:
            return REDACTED
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, val in value.items():
            if _key_sensitive(key):
                out[key] = REDACTED
            else:
                out[key] = sanitize_value(val)
        return out
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    if isinstance(value, set):
        return {sanitize_value(item) for item in value}
    # Fallback for odd JSON-serializable types — stringify then redact.
    return redact_string(str(value))


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_value(payload)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
