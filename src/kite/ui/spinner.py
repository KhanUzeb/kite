"""Wait spinner — never stay silent more than ~1s."""

from __future__ import annotations

import itertools
import sys
import threading
import time
from typing import TextIO

FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class WaitSpinner:
    def __init__(self, stream: TextIO | None = None, *, delay: float = 1.0, label: str = "thinking"):
        self.stream = stream or sys.stderr
        self.delay = delay
        self.label = label
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._shown = False
        self._thread: threading.Thread | None = None

    def kick(self, label: str | None = None) -> None:
        with self._lock:
            self._last = time.monotonic()
            if label:
                self.label = label
            if self._shown:
                self._clear()
                self._shown = False

    def start(self) -> None:
        self._stop.clear()
        self.kick()
        self._thread = threading.Thread(target=self._run, name="kite-spinner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.4)
            self._thread = None
        with self._lock:
            if self._shown:
                self._clear()
                self._shown = False

    def _clear(self) -> None:
        try:
            self.stream.write("\r\033[K")
            self.stream.flush()
        except OSError:
            pass

    def _run(self) -> None:
        frames = itertools.cycle(FRAMES)
        while not self._stop.is_set():
            time.sleep(0.08)
            with self._lock:
                idle = time.monotonic() - self._last
                if idle < self.delay:
                    continue
                frame = next(frames)
                line = f"  {frame} {self.label}"
                try:
                    self.stream.write("\r" + line + "\033[K")
                    self.stream.flush()
                    self._shown = True
                except OSError:
                    return
