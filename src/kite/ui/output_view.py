"""Readable tool/text output — unwrap JSON envelopes, use the full terminal width."""

from __future__ import annotations

import json
from typing import Any

from rich.text import Text

_ENVELOPE_KEYS = frozenset(
    {
        "ok",
        "output",
        "error",
        "summary",
        "preview",
        "warnings",
        "metadata",
        "exit_code",
        "duration_ms",
        "blocked",
        "diff",
        "secrets_redacted",
        "cwd",
        "path",
        "count",
        "submitted",
        "submission",
        "job_id",
        "id",
    }
)


def _try_json(raw: str) -> Any:
    text = (raw or "").strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def format_viewable_output(raw: str) -> str:
    """Turn a tool result into text a human can read (not a one-line JSON blob)."""
    if not raw:
        return ""
    parsed = _try_json(raw)
    if parsed is None:
        return raw.rstrip("\n") + ("\n" if raw.endswith("\n") else "")
    unwrapped = _unwrap_envelope(parsed)
    if isinstance(unwrapped, str):
        nested = _try_json(unwrapped)
        if nested is not None:
            return json.dumps(nested, indent=2, ensure_ascii=False) + "\n"
        return unwrapped.rstrip("\n") + ("\n" if unwrapped.endswith("\n") or "\n" in unwrapped else "")
    return json.dumps(unwrapped, indent=2, ensure_ascii=False) + "\n"


def _unwrap_envelope(parsed: Any) -> Any:
    if not isinstance(parsed, dict):
        return parsed
    keys = set(parsed)
    if "output" in parsed and keys <= _ENVELOPE_KEYS:
        inner = parsed.get("output")
        if inner is None or inner == "":
            err = parsed.get("error")
            if err:
                return err
            return ""
        return inner
    if "error" in parsed and keys <= _ENVELOPE_KEYS and not parsed.get("output"):
        return parsed.get("error") or parsed
    return parsed


_THINKING_KEYS = ("reasoning", "thought", "thinking", "content", "text", "output", "message")


def format_thinking_text(raw: str) -> str:
    """Same as viewable output, plus common model reasoning JSON wrappers."""
    if not raw:
        return ""
    parsed = _try_json(raw)
    if isinstance(parsed, dict):
        for key in _THINKING_KEYS:
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                return format_thinking_text(val)
        return json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
    if isinstance(parsed, list):
        return json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
    return format_viewable_output(raw)


def render_thinking_block(text: str) -> Text:
    """Full-width thinking prose — no left rail, drag-select friendly."""
    raw = format_thinking_text(text).rstrip("\n")
    out = Text()
    if not raw:
        return out
    for line in raw.splitlines():
        out.append(line + "\n", style="kite.thinking")
    return out


def render_output_block(text: str, *, expanded: bool, limit: int = 12) -> Text:
    """Full-width body — no extra gutter so drag-select and wrap stay even."""
    raw = format_viewable_output(text).rstrip("\n")
    if not raw:
        return Text()
    lines = raw.splitlines()
    shown = lines if expanded else lines[:limit]
    out = Text()
    for line in shown:
        out.append(line + "\n", style="kite.terminal")
    extra = len(lines) - len(shown)
    if extra > 0:
        from kite.ui.theme import glyph

        hint = "/collapse" if expanded else "/expand"
        mark = glyph("expand") if expanded else glyph("collapse")
        out.append(f"{mark} +{extra} lines  {hint}\n", style="kite.muted")
    return out
