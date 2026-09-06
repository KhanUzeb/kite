"""Wait spinner — beautifului-style loaders with shimmer and elapsed time."""

from __future__ import annotations

import sys
import threading
import time
from typing import TextIO

from kite.ui.animations import (
    default_loader_style,
    format_elapsed,
    loader_glyph,
    shimmer_ansi,
)


class WaitSpinner:
    """Animated loader on stderr after brief idle. Never stay silent.

    Writes to the live ``sys.stderr`` each frame so ``patch_stdout`` (which
    redirects stderr while the composer is pinned) can place text above the
    prompt. Prefer disabling this spinner while ``state.busy`` — the toolbar
    owns activity chrome then.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        delay: float = 0.45,
        label: str = "thinking",
        style: str | None = None,
        shimmer: bool = True,
    ):
        self._stream = stream
        self.delay = delay
        self._delay_active = delay
        self.label = label
        self.style = style or default_loader_style()
        self.shimmer = shimmer
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._started: float | None = None
        self._tick = 0
        self._stop = threading.Event()
        self._shown = False
        self._thread: threading.Thread | None = None

    @property
    def stream(self) -> TextIO:
        return self._stream if self._stream is not None else sys.stderr

    @stream.setter
    def stream(self, value: TextIO | None) -> None:
        self._stream = value

    def kick(self, label: str | None = None, *, fast: bool = False) -> None:
        with self._lock:
            self._last = time.monotonic()
            if fast:
                self._delay_active = 0.15
            else:
                self._delay_active = self.delay
            if label:
                self.label = label
            if self._shown:
                self._clear()
                self._shown = False

    def start(self) -> None:
        self._stop.clear()
        self._started = time.monotonic()
        self._tick = 0
        self.kick()
        self._thread = threading.Thread(target=self._run, name="kite-spinner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.15)
            self._thread = None
        with self._lock:
            if self._shown:
                self._clear()
                self._shown = False
        self._started = None

    def _clear(self) -> None:
        try:
            self.stream.write("\r\033[K")
            self.stream.flush()
        except OSError:
            pass

    def _format_line(self) -> str:
        glyph = loader_glyph(self.style, self._tick)
        elapsed = ""
        if self._started is not None:
            elapsed = f"  {format_elapsed(time.monotonic() - self._started)}"
        label = self.label
        if self.shimmer and label:
            label_part = shimmer_ansi(label, self._tick)
            return f"  {glyph}  {label_part}{elapsed}\033[0m"
        return f"  {glyph}  {label}{elapsed}"

    def _run(self) -> None:
        while not self._stop.wait(0.06):
            with self._lock:
                idle = time.monotonic() - self._last
                if idle < self._delay_active:
                    continue
                self._tick += 1
                line = self._format_line()
                try:
                    self.stream.write("\r" + line + "\033[K")
                    self.stream.flush()
                    self._shown = True
                except OSError:
                    return
