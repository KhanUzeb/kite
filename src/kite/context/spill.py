"""Large-output spill (§5): file + path/size/tail instead of truncating.

Truncating loses data and inlining bloats every later request (the prefix is
resent each turn). Spilled outputs keep a short tail in context while the full
body stays searchable via tail/grep/read ranges.
"""

from __future__ import annotations

import time
from pathlib import Path

DEFAULT_SPILL_CHARS = 12_000
TAIL_CHARS = 2_000


def spill_text(
    text: str,
    *,
    cwd: str | Path = ".",
    prefix: str = "tool",
    max_chars: int = DEFAULT_SPILL_CHARS,
) -> dict[str, object]:
    """Write `text` to `.kite/spills/` when over budget; return pointer metadata."""
    if len(text) <= max_chars:
        return {"spilled": False, "output": text}
    root = Path(cwd).expanduser().resolve()
    spill_dir = root / ".kite" / "spills"
    try:
        spill_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"spilled": False, "output": text[-max_chars:], "truncated": True}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = spill_dir / f"{prefix}-{stamp}-{abs(hash(text)) % 100000:05d}.log"
    try:
        path.write_text(text, encoding="utf-8", errors="replace")
    except OSError:
        return {"spilled": False, "output": text[-max_chars:], "truncated": True}
    tail = text[-TAIL_CHARS:]
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    pointer = (
        f"[spilled {len(text):,} chars → {rel} "
        f"({path.stat().st_size:,} bytes); tail below; "
        f"use bash (tail/grep/sed -n) or read offset/limit for more]\n{tail}"
    )
    return {"spilled": True, "output": pointer, "path": str(path), "size": len(text), "tail": tail}
