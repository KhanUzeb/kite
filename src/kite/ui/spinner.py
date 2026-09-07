"""Wait spinner — beautifului-style loaders with shimmer and elapsed time."""

from __future__ import annotations

import atexit
import sys
import threading
import time
import weakref
from typing import TextIO

from kite.ui.animations import (
    default_loader_style,
    format_elapsed,
    loader_glyph,
    shimmer_ansi,
)

# Keep weak refs so atexit / pytest teardown can stop daemon writers before
# interpreter finalization (Python 3.11 can abort on stderr lock otherwise).
_ACTIVE: weakref.WeakSet[WaitSpinner] = weakref.WeakSet()
_ACTIVE_LOCK = threading.Lock()


def stop_all_spinners() -> None:
    """Stop every live WaitSpinner (safe from tests and atexit)."""
    with _ACTIVE_LOCK:
        spinners = list(_ACTIVE)
    for spinner in spinners:
        try:
            spinner.stop()
        except Exception:
            pass


def _atexit_stop() -> None:
    stop_all_spinners()


atexit.register(_atexit_stop)


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
        self.stop()
        self._stop.clear()
        self._started = time.monotonic()
        self._tick = 0
        self.kick()
        with _ACTIVE_LOCK:
            _ACTIVE.add(self)
        # Avoid daemon stderr writers under pytest / pipes — they race interpreter
        # shutdown on Linux 3.11 (`_enter_buffered_busy` fatal abort).
        if os_environ_pytest() or not _stream_is_tty(self.stream):
            self._thread = None
            return
        self._thread = threading.Thread(target=self._run, name="kite-spinner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)
        with self._lock:
            if self._shown:
                self._clear()
                self._shown = False
        self._started = None
        with _ACTIVE_LOCK:
            _ACTIVE.discard(self)

    def _clear(self) -> None:
        try:
            if _interpreter_finalizing():
                return
            self.stream.write("\r\033[K")
            self.stream.flush()
        except Exception:
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
        while not self._stop.wait(0.12):
            if _interpreter_finalizing():
                return
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
                except Exception:
                    return


def os_environ_pytest() -> bool:
    import os

    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _stream_is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _interpreter_finalizing() -> bool:
    is_finalizing = getattr(sys, "is_finalizing", None)
    if callable(is_finalizing):
        try:
            return bool(is_finalizing())
        except Exception:
            return False
    return False
