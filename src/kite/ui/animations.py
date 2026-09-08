"""Terminal animations — plain-symbol loaders (no braille or emoji glyphs)."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Literal

LoaderStyle = Literal["spin", "dots", "orbit", "grid", "wave"]

_GRID_STRIP = "-=+#"


def _frame_spin(tick: int) -> str:
    return "|/-\\"[tick % 4]


def _frame_dots(tick: int) -> str:
    phases = ("*..", ".*.", "..*", "...")
    return phases[(tick // 2) % len(phases)]


def _frame_orbit(tick: int) -> str:
    phases = ("(\\", "/)", "(/", "\\)")
    return phases[tick % len(phases)]


def _frame_wave(tick: int) -> str:
    phases = ("~^", "^-", "-~", "~-")
    return phases[tick % len(phases)]


def _frame_grid(tick: int) -> str:
    n = len(_GRID_STRIP)
    head = tick % n
    return "".join(_GRID_STRIP[(head + i) % n] for i in range(4))


_LOADER: dict[str, Callable[[int], str]] = {
    "spin": _frame_spin,
    "dots": _frame_dots,
    "orbit": _frame_orbit,
    "wave": _frame_wave,
    "grid": _frame_grid,
}


def default_loader_style() -> LoaderStyle:
    raw = (os.environ.get("KITE_LOADER") or "grid").strip().lower()
    if raw in _LOADER:
        return raw  # type: ignore[return-value]
    return "grid"


def loader_glyph(style: str, tick: int) -> str:
    fn = _LOADER.get(style, _frame_grid)
    return fn(tick)


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}m{secs:02d}s"


def shimmer_ansi(text: str, tick: int) -> str:
    """Sweep a bright highlight across label characters."""
    if not text:
        return ""
    pos = tick % max(1, len(text))
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch == " ":
            out.append(ch)
            continue
        if i == pos:
            out.append(f"\033[1m{ch}\033[0m")
        else:
            out.append(f"\033[2m{ch}\033[0m")
    return "".join(out)
