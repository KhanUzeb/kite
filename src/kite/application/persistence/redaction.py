"""Redact sensitive values before persistence."""

from __future__ import annotations

import json
import re
from typing import Any

_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
)


def redact_text(text: str) -> str:
    out = text
    for pat in _PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(payload)
    return json.loads(redact_text(raw))
