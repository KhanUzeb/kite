"""Repair common malformed tool-call JSON from streaming models."""

from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def repair_tool_arguments(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Try to parse tool arguments; return (args, error_message)."""
    text = (raw or "").strip()
    if not text:
        return {}, None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, None
        return {"value": parsed}, None
    except json.JSONDecodeError:
        pass

    stripped = _FENCE_RE.sub("", text).strip()
    if stripped != text:
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed, None
            return {"value": parsed}, None
        except json.JSONDecodeError:
            pass

    # Trailing comma before } or ]
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    if fixed != text:
        try:
            parsed = json.loads(fixed)
            if isinstance(parsed, dict):
                return parsed, None
            return {"value": parsed}, None
        except json.JSONDecodeError:
            pass

    # Single-quoted keys/values (invalid JSON but models sometimes emit)
    if "'" in text and '"' not in text and text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, dict):
                return parsed, None
        except json.JSONDecodeError:
            pass

    return None, f"Invalid tool arguments JSON after repair attempts"
