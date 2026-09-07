"""Token-aware shaping of tool observations sent to the model."""

from __future__ import annotations

import json
from typing import Any

DEFAULT_OBSERVATION_MAX_CHARS = 5_000
_LINE_ELIDE_THRESHOLD = 80


def _line_aware_elide(text: str, max_chars: int) -> str:
    """Keep first/last lines for multiline tool output; head/tail for single blocks."""
    lines = text.splitlines()
    if len(lines) >= _LINE_ELIDE_THRESHOLD:
        head_n, tail_n = 35, 12
        head = "\n".join(lines[:head_n])
        tail = "\n".join(lines[-tail_n:])
        omitted = len(lines) - head_n - tail_n
        body = f"{head}\n...[{omitted} lines elided]...\n{tail}"
        if len(body) <= max_chars:
            return body
    head = max_chars // 2
    tail = max_chars // 4
    omitted = len(text) - head - tail
    return f"{text[:head]}\n...<elided {omitted:,} chars>...\n{text[-tail:]}"


def observation_content(output: dict[str, Any], *, max_chars: int = DEFAULT_OBSERVATION_MAX_CHARS) -> str:
    """Return model-facing tool output, preferring summaries when eliding large payloads."""
    raw = output.get("output") or output.get("error") or ""
    if not isinstance(raw, str):
        raw = str(raw)
    if not raw.strip():
        return json.dumps(output, default=str)

    if len(raw) <= max_chars:
        return raw

    summary = str(output.get("summary") or "").strip()
    if summary:
        head = max_chars // 3
        tail = max_chars // 5
        budget = max_chars - head - tail - len(summary) - 80
        if budget > 200:
            omitted = len(raw) - head - tail
            return (
                f"{raw[:head]}\n\n"
                f"...[elided {omitted:,} chars; summary below]...\n\n"
                f"{summary}\n\n"
                f"...[tail]...\n{raw[-tail:]}"
            )

    head = max_chars // 2
    tail = max_chars // 4
    omitted = len(raw) - head - tail
    return _line_aware_elide(raw, max_chars) if "\n" in raw else (
        f"{raw[:head]}\n...<elided {omitted:,} chars>...\n{raw[-tail:]}"
    )
