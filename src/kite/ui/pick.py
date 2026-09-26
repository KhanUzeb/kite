"""Numbered pickers — typed input plus a raw-key list (arrows / wheel)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

_PICK_SHOW = 40
REFRESH_PICK = "__refresh__"


def can_use_radiolist() -> bool:
    """Fullscreen prompt_toolkit dialogs break on Windows and inside a running REPL."""
    if sys.platform == "win32":
        return False
    from kite.util.tty import is_interactive_tty

    if not is_interactive_tty():
        return False
    try:
        from prompt_toolkit.application.current import get_app_or_none

        if get_app_or_none() is not None:
            return False
    except Exception:
        return False
    return True


def provider_sort_key(
    *,
    name: str,
    oauth_first: bool,
    is_oauth: bool,
    ready: bool,
    recommended_index: int,
) -> tuple[int, int, int, str]:
    """Canonical provider-picker ordering: oauth first, then ready, then recommended."""
    oauth_rank = 0 if oauth_first and is_oauth else 1
    return (oauth_rank, 0 if ready else 1, recommended_index, name)

_PAGE_NEXT = {"+", ">", "more", "pgdn", "pagedown"}
_PAGE_PREV = {"-", "<", "prev", "pgup", "pageup"}


def can_prompt() -> bool:
    """True when we can ask a question (stdin TTY; we print prompts on stderr)."""
    from kite.util.tty import is_interactive_tty

    if not is_interactive_tty(require_stdout=False):
        return False
    return sys.stderr.isatty()


def _console_is_scripted(console: Console) -> bool:
    """Tests and scripts drive `console.input` — stay on the typed path."""
    inp = getattr(console, "input", None)
    if inp is None:
        return False
    if getattr(inp, "side_effect", None) is not None or getattr(inp, "return_value", None) is not None:
        return True
    return "Mock" in type(inp).__name__


def can_scroll_pick() -> bool:
    """Raw-key picker (no prompt_toolkit Application — that broke Windows selects)."""
    import os

    if os.environ.get("KITE_TYPED_PICK", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return can_prompt()


def _read_choice(console: Console, prompt: str) -> str:
    """Read a line. Tests use ``console.input``; Windows TTY uses stdin (Rich is flaky)."""
    if _console_is_scripted(console):
        return console.input(prompt).strip()
    if sys.platform == "win32":
        sys.stderr.write(prompt)
        sys.stderr.flush()
        return input().strip()
    try:
        return console.input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise
    except Exception:
        sys.stderr.write(prompt)
        sys.stderr.flush()
        return input().strip()


def numbered_pick(
    console: Console,
    items: list[tuple[str, str]],
    *,
    current: str | None = None,
    title: str,
    noun: str,
    show: int = _PICK_SHOW,
    refreshable: bool = False,
) -> str | None:
    """Pick from a list.

    Interactive TTY: arrows, Page Up/Down, wheel/trackpad (Windows console), type to
    filter, Enter. Scripted/tests: number, id, substring, ``+``/``-`` pages, ``r``.
    """
    if not items:
        from kite.ui.empty import render_empty

        try:
            console.print(render_empty(f"no {noun}s", hint="nothing to pick"))
        except Exception:
            pass
        return None
    if can_scroll_pick() and not _console_is_scripted(console):
        try:
            return _raw_pick(
                console,
                items,
                current=current,
                title=title,
                noun=noun,
                show=show,
                refreshable=refreshable,
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[kite.pending]Cancelled[/]")
            return None
        except Exception:
            pass
    return _typed_pick(
        console,
        items,
        current=current,
        title=title,
        noun=noun,
        show=show,
        refreshable=refreshable,
    )


def _raw_pick(
    console: Console,
    items: list[tuple[str, str]],
    *,
    current: str | None,
    title: str,
    noun: str,
    show: int,
    refreshable: bool,
) -> str | None:
    """In-place list driven by raw keys (and Windows mouse wheel)."""
    _ensure_vt_output()
    pool = list(items)
    state = {"filter": "", "cursor": 0, "offset": 0}
    ids = [item_id for item_id, _ in pool]
    if current and current in ids:
        state["cursor"] = ids.index(current)
    drawn = {"lines": 0}

    def filtered() -> list[tuple[str, str]]:
        needle = state["filter"].lower()
        if not needle:
            return pool
        return [
            (item_id, label)
            for item_id, label in pool
            if needle in item_id.lower() or needle in label.lower()
        ]

    def clamp() -> list[tuple[str, str]]:
        rows = filtered()
        if not rows:
            state["cursor"] = 0
            state["offset"] = 0
            return rows
        state["cursor"] = max(0, min(state["cursor"], len(rows) - 1))
        if state["cursor"] < state["offset"]:
            state["offset"] = state["cursor"]
        elif state["cursor"] >= state["offset"] + show:
            state["offset"] = state["cursor"] - show + 1
        return rows

    def move(delta: int) -> None:
        rows = filtered()
        if rows:
            state["cursor"] = max(0, min(state["cursor"] + delta, len(rows) - 1))
            clamp()

    def paint() -> None:
        from kite.ui.credentials import render_pick_list

        rows = clamp()
        view = rows[state["offset"] : state["offset"] + show]
        extra = max(0, len(rows) - len(view))
        heading = title if not state["filter"] else f"{title}  ·  {len(rows)} matches"
        if state["filter"]:
            heading = f"{heading}  [{state['filter']}]"
        panel = render_pick_list(
            view,
            title=heading,
            current=current,
            extra=extra,
            noun=noun,
            refreshable=refreshable,
            page_hint=extra > 0,
            cursor=state["cursor"] - state["offset"] if view else None,
        )
        if drawn["lines"]:
            sys.stderr.write(f"\x1b[{drawn['lines']}A\x1b[J")
            sys.stderr.flush()
        with console.capture() as cap:
            console.print(panel)
        text = cap.get()
        sys.stderr.write(text)
        if not text.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()
        drawn["lines"] = text.count("\n") + (0 if text.endswith("\n") else 1)
        drawn["n_view"] = len(view)
        end_y = _stderr_cursor_y()
        if end_y is not None:
            drawn["start_y"] = end_y - drawn["lines"]
            drawn["item_y0"] = drawn["start_y"] + 1

    paint()
    reader = _event_reader(drawn)
    try:
        while True:
            ev = reader()
            if ev is None:
                continue
            _pick_debug(f"loop ev={ev!r} filter={state['filter']!r}")
            if isinstance(ev, str) and ev.startswith(("goto:", "pick:")):
                try:
                    vis = int(ev.split(":", 1)[1])
                except ValueError:
                    continue
                rows = clamp()
                if 0 <= vis < min(show, len(rows)):
                    state["cursor"] = state["offset"] + vis
                    if ev.startswith("pick:"):
                        return rows[state["cursor"]][0]
                    paint()
                continue
            if ev in {"esc", "ctrl-c"}:
                console.print("[kite.pending]Cancelled[/]")
                return None
            if ev == "enter":
                rows = clamp()
                if not rows:
                    return None
                if state["filter"].isdigit():
                    idx = int(state["filter"])
                    view = rows[state["offset"] : state["offset"] + show]
                    if 1 <= idx <= len(view):
                        return view[idx - 1][0]
                    if 1 <= idx <= len(rows):
                        return rows[idx - 1][0]
                return rows[state["cursor"]][0]
            if ev == "up":
                move(-1)
            elif ev == "down":
                move(1)
            elif ev == "pageup":
                move(-show)
            elif ev == "pagedown":
                move(show)
            elif ev == "home":
                state["cursor"] = 0
                clamp()
            elif ev == "end":
                state["cursor"] = max(0, len(filtered()) - 1)
                clamp()
            elif ev == "backspace":
                state["filter"] = state["filter"][:-1]
                state["cursor"] = 0
            elif ev == "refresh" or (ev == "r" and refreshable and not state["filter"]):
                return REFRESH_PICK
            elif ev == "q" and not state["filter"]:
                console.print("[kite.pending]Cancelled[/]")
                return None
            elif isinstance(ev, str) and len(ev) == 1 and ev.isprintable():
                state["filter"] += ev
                state["cursor"] = 0
            else:
                continue
            paint()
    finally:
        close = getattr(reader, "close", None)
        if close is not None:
            close()


def view_index_from_mouse(*, mouse_y: int, item_y0: int, n_view: int) -> int | None:
    """Map a console row to a visible pick-list index (title is above the items)."""
    if n_view <= 0:
        return None
    idx = int(mouse_y) - int(item_y0)
    if 0 <= idx < n_view:
        return idx
    return None


def _stderr_cursor_y() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        from prompt_toolkit.win32_types import CONSOLE_SCREEN_BUFFER_INFO

        k32 = ctypes.windll.kernel32
        buf = CONSOLE_SCREEN_BUFFER_INFO()
        handle = k32.GetStdHandle(-12)
        if k32.GetConsoleScreenBufferInfo(handle, ctypes.byref(buf)):
            return int(buf.dwCursorPosition.Y)
    except Exception:
        return None
    return None


def _pick_debug(msg: str) -> None:
    """Append picker diagnostics when KITE_PICK_DEBUG is set.

    Log file: %TEMP%/kite-pick-debug.log (or $TMPDIR on POSIX).
    Used to identify which raw reader a terminal ends up on.
    """
    import os

    if not os.environ.get("KITE_PICK_DEBUG"):
        return
    try:
        import tempfile

        path = os.path.join(tempfile.gettempdir(), "kite-pick-debug.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


def _consume_event(buf: str, drawn: dict) -> tuple[str | None, str, bool]:
    """Parse one event from the front of ``buf``.

    Returns ``(event, rest, need_more)``. ``need_more`` means the buffer
    ends mid-escape-sequence — the caller must wait for more bytes
    instead of emitting ``[`` / ``B`` fragments into the filter.
    Shared by the POSIX and msvcrt readers so split ANSI delivery
    (pipes, conpty chunking) can never pollute type-to-filter.
    """
    if not buf:
        return None, buf, False
    if buf[0] != "\x1b":
        ch = buf[0]
        rest = buf[1:]
        if ch in "\r\n":
            return "enter", rest, False
        if ch == "\x03":
            return "ctrl-c", rest, False
        if ch in "\x7f\x08":
            return "backspace", rest, False
        if ch == "\x12":
            return "refresh", rest, False
        return (ch if ch.isprintable() else None), rest, False
    # Buffer starts with ESC — need at least one more byte to decide.
    if len(buf) == 1:
        return None, buf, True
    second = buf[1]
    if second not in {"[", "O"}:
        # Lone ESC (or Alt+key) — report cancel, keep the rest.
        return "esc", buf[1:], False
    if second == "O":
        if len(buf) < 3:
            return None, buf, True
        return _posix_key(buf[:3]), buf[3:], False
    # CSI: ESC [ params... final
    import re

    m = re.match(r"^\x1b\[<[0-9;]*[Mm]", buf)
    if m:
        seq = m.group(0)
        return _posix_mouse(seq, drawn), buf[len(seq):], False
    if re.match(r"^\x1b\[<[0-9;]*$", buf):
        return None, buf, True  # incomplete SGR mouse — wait for M/m
    if re.match(r"^\x1b\[M...?$", buf, re.DOTALL):
        # Legacy X10 mouse — swallow (picker uses SGR anyway).
        if len(buf) >= 6:
            return None, buf[6:], False
        return None, buf, True
    m = re.match(r"^\x1b\[[0-9;:<=>\?]*[@-~]", buf)
    if m:
        seq = m.group(0)
        return _posix_key(seq), buf[len(seq):], False
    # ESC [ without a final byte yet — wait for it.
    if re.match(r"^\x1b\[[0-9;:<=>\?]*$", buf):
        return None, buf, True
    # Unknown ESC lead-in — swallow it, never leak into filter.
    return None, buf[2:], False


def _event_reader(drawn: dict):
    if sys.platform == "win32":
        try:
            reader = _WinEvents(drawn)
        except OSError as exc:
            _pick_debug(f"reader=_WinKeyOnly fallback ({exc!r})")
            return _WinKeyOnly(drawn)
        _pick_debug("reader=_WinEvents")
        return reader
    _pick_debug("reader=_PosixEvents")
    return _PosixEvents(drawn)


def _ensure_vt_output() -> None:
    """Best-effort: enable VT processing so in-place repaint codes work."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-12)  # STD_ERROR_HANDLE
        mode = wintypes.DWORD()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return
        if not mode.value & 0x0004:
            k32.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        return


class _WinKeyOnly:
    """msvcrt fallback when console mouse mode cannot be enabled.

    Reads stdin as an ANSI byte stream (pipes, mintty, VT input) with a
    persistent buffer: split escape sequences are coalesced across calls,
    so ``[B`` / ``[<35;..M`` fragments never leak into the type-to-filter
    buffer as ``[[B[B[`` junk. A lone ESC still cancels, but only after a
    short settle wait proves no continuation is coming.
    """

    _SETTLE_ROUNDS = 6
    _SETTLE_SLEEP = 0.015

    def __init__(self, drawn: dict | None = None) -> None:
        import msvcrt

        self._msvcrt = msvcrt
        self._drawn = drawn or {}
        self._buf = ""

    def _settle(self) -> bool:
        """Poll briefly for continuation bytes of a split sequence.

        Returns True when the buffer grew. A lone ESC is only reported
        as cancel when a full settle passes with zero new bytes.
        """
        import time

        grew = False
        for _ in range(self._SETTLE_ROUNDS):
            _, _, need_more = _consume_event(self._buf, self._drawn)
            if not need_more:
                break
            time.sleep(self._SETTLE_SLEEP)
            while self._msvcrt.kbhit():
                self._buf += self._msvcrt.getwch()
                grew = True
        return grew

    def __call__(self) -> str | None:
        msvcrt = self._msvcrt
        new_data = False
        if not self._buf:
            ch = msvcrt.getwch()  # blocking: wait for the next key
            if ch in {"\x00", "\xe0"}:
                code = msvcrt.getwch()
                return {
                    "H": "up",
                    "P": "down",
                    "I": "pageup",
                    "Q": "pagedown",
                    "G": "home",
                    "O": "end",
                }.get(code)
            self._buf += ch
            new_data = True
        else:
            before = len(self._buf)
            while msvcrt.kbhit():
                self._buf += msvcrt.getwch()
            new_data = len(self._buf) > before
        new_data |= self._settle()
        while self._buf:
            ev, rest, need_more = _consume_event(self._buf, self._drawn)
            if need_more:
                # Still split after settling. Lone ESC with zero new bytes
                # → cancel; otherwise hold the partial for the next call.
                if self._buf == "\x1b" and not new_data:
                    self._buf = ""
                    _pick_debug("ev='esc' (lone)")
                    return "esc"
                _pick_debug(f"hold partial buf={self._buf!r}")
                return None
            self._buf = rest
            if ev is None and rest:
                continue  # swallowed junk, more input queued — keep parsing
            _pick_debug(f"ev={ev!r}")
            return ev
        return None

    def close(self) -> None:
        return None


class _WinEvents:
    """Windows keys + click/drag/wheel via ReadConsoleInput (picker only)."""

    def __init__(self, drawn: dict) -> None:
        import ctypes
        from ctypes import wintypes

        from prompt_toolkit.win32_types import INPUT_RECORD

        self._drawn = drawn
        self._k32 = ctypes.windll.kernel32
        self._h = self._k32.GetStdHandle(-10)
        self._old = wintypes.DWORD()
        if not self._k32.GetConsoleMode(self._h, ctypes.byref(self._old)):
            raise OSError("no console")
        # Mouse on, Quick Edit off so drag events reach us (restored on close).
        mode = (int(self._old.value) | 0x0010 | 0x0008 | 0x0080 | 0x0001) & ~0x0040 & ~0x0002 & ~0x0004
        if not self._k32.SetConsoleMode(self._h, mode):
            raise OSError("console mode")
        self._IR = INPUT_RECORD
        self._down = False
        self._closed = False

    def __call__(self) -> str | None:
        import ctypes
        from ctypes import wintypes

        rec = self._IR()
        n = wintypes.DWORD()
        if not self._k32.ReadConsoleInputW(self._h, ctypes.byref(rec), 1, ctypes.byref(n)) or n.value != 1:
            return None
        if rec.EventType == 1:
            key = rec.Event.KeyEvent
            if not key.KeyDown:
                return None
            vk = int(key.VirtualKeyCode)
            ch = key.uChar.UnicodeChar or ""
            mapped = {
                38: "up",
                40: "down",
                33: "pageup",
                34: "pagedown",
                36: "home",
                35: "end",
                13: "enter",
                27: "esc",
                8: "backspace",
            }.get(vk)
            if mapped:
                return mapped
            if vk == 67 and (int(key.ControlKeyState) & 0x0008):
                return "ctrl-c"
            if vk == 82 and (int(key.ControlKeyState) & 0x0008):
                return "refresh"
            return ch if ch and ch.isprintable() else None
        if rec.EventType == 2:
            return self._mouse(rec.Event.MouseEvent)
        return None

    def _mouse(self, mouse) -> str | None:
        import ctypes

        flags = int(mouse.EventFlags)
        buttons = int(mouse.ButtonState)
        if flags & 0x0004:  # WHEELED
            delta = ctypes.c_short((buttons >> 16) & 0xFFFF).value
            return "up" if delta > 0 else "down"
        y = int(mouse.MousePosition.Y)
        vis = view_index_from_mouse(
            mouse_y=y,
            item_y0=int(self._drawn.get("item_y0", -1)),
            n_view=int(self._drawn.get("n_view", 0)),
        )
        left = bool(buttons & 0x1)
        if left:
            self._down = True
            if vis is not None:
                return f"goto:{vis}"
            return None
        if self._down:
            self._down = False
            if vis is not None:
                return f"goto:{vis}"
            return "enter"
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._k32.SetConsoleMode(self._h, self._old)
        except Exception:
            pass


class _PosixEvents:
    def __init__(self, drawn: dict) -> None:
        import termios
        import tty

        self._drawn = drawn
        self._fd = sys.stdin.fileno()
        self._termios = termios
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        sys.stderr.write("\x1b[?1000h\x1b[?1002h\x1b[?1006h")
        sys.stderr.flush()
        self._closed = False
        self._buf = ""

    def _drain(self) -> None:
        """Append every immediately-available byte (bulk, not 1-byte)."""
        import os
        import select

        for _ in range(32):
            if not select.select([self._fd], [], [], 0)[0]:
                break
            try:
                chunk = os.read(self._fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            self._buf += chunk.decode("utf-8", errors="replace")
            if len(chunk) < 4096:
                break

    def _extract(self) -> str | None | bool:
        """Parse one event from the front of the buffer.

        Returns False when more bytes are needed for an incomplete ESC
        sequence (caller waits instead of leaking ``[B`` fragments).
        """
        ev, rest, need_more = _consume_event(self._buf, self._drawn)
        if need_more:
            return False
        self._buf = rest
        return ev

    def __call__(self) -> str | None:
        import os
        import select

        new_data = False
        if not self._buf:
            ready, _, _ = select.select([self._fd], [], [], 0.5)
            if not ready:
                return None
            try:
                chunk = os.read(self._fd, 4096)
            except OSError:
                return None
            if not chunk:
                return "esc"
            self._buf += chunk.decode("utf-8", errors="replace")
            new_data = True
        else:
            before = len(self._buf)
            self._drain()
            new_data = len(self._buf) > before
        # Coalesce split escape sequences: keep draining briefly while the
        # buffer ends mid-sequence instead of emitting ``[`` / ``B`` pieces.
        for _ in range(5):
            ev = self._extract()
            if ev is not False:
                if ev is None and self._buf:
                    # Swallowed an unknown sequence but more input is queued
                    # (e.g. mouse motion + click) — keep parsing, don't idle.
                    continue
                return ev
            import time as _time

            _time.sleep(0.02)
            before = len(self._buf)
            self._drain()
            if len(self._buf) > before:
                new_data = True
            else:
                break
        ev = self._extract()
        if ev is False:
            # Lone ESC with zero new bytes after settling → cancel.
            # Anything else partial is held for the next call, never leaked.
            if self._buf == "\x1b" and not new_data:
                self._buf = ""
                return "esc"
            return None
        return ev

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            sys.stderr.write("\x1b[?1006l\x1b[?1002l\x1b[?1000l")
            sys.stderr.flush()
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old)
        except Exception:
            pass


def _posix_key(seq: str) -> str | None:
    """Decode normal and application-cursor terminal key sequences."""
    direct = {
        "\x1b[A": "up",
        "\x1b[B": "down",
        "\x1b[5~": "pageup",
        "\x1b[6~": "pagedown",
        "\x1b[H": "home",
        "\x1b[F": "end",
        "\x1bOA": "up",
        "\x1bOB": "down",
        "\x1bOH": "home",
        "\x1bOF": "end",
        "\x1b": "esc",
    }
    if seq in direct:
        return direct[seq]
    if seq.startswith("\x1b[") and seq[-1:] in {"A", "B", "H", "F"}:
        return {
            "A": "up",
            "B": "down",
            "H": "home",
            "F": "end",
        }[seq[-1]]
    return None


def _posix_mouse(seq: str, drawn: dict) -> str | None:
    # SGR: ESC [ < btn ; x ; y M/m  — drag uses 1002 (code + 32).
    if not seq.startswith("\x1b[<") or len(seq) < 6:
        return None
    end = seq[-1]
    try:
        btn, _x, y_s = seq[3:-1].split(";")
        code = int(btn)
        y = int(y_s) - 1
    except ValueError:
        return None
    if code & 64:
        return "down" if code & 1 else "up"
    vis = view_index_from_mouse(
        mouse_y=y,
        item_y0=int(drawn.get("item_y0", -1)),
        n_view=int(drawn.get("n_view", 0)),
    )
    if (code & 3) == 0 and end == "M":
        return f"goto:{vis}" if vis is not None else None
    if (code & 3) == 0 and end == "m":
        return f"pick:{vis}" if vis is not None else "enter"
    return None


def _typed_pick(
    console: Console,
    items: list[tuple[str, str]],
    *,
    current: str | None,
    title: str,
    noun: str,
    show: int,
    refreshable: bool,
) -> str | None:
    from kite.ui.credentials import render_pick_list

    pool = list(items)
    offset = 0

    while True:
        if offset >= len(pool):
            offset = max(0, len(pool) - show)
        shown = list(pool[offset : offset + show])
        if current and not any(item_id == current for item_id, _ in shown):
            for pair in pool:
                if pair[0] == current:
                    shown = [pair, *shown][:show]
                    break

        extra_after = max(0, len(pool) - offset - len(shown))
        extra = extra_after + offset
        console.print(
            render_pick_list(
                shown,
                title=title if pool == items else f"{title}  ·  {len(pool)} matches",
                current=current,
                extra=extra,
                noun=noun,
                refreshable=refreshable,
                page_hint=extra > 0,
            )
        )

        prompt = f"Pick {noun} (number, name, filter, +/− page"
        if refreshable:
            prompt += ", r refresh"
        prompt += "): "
        try:
            raw = _read_choice(console, prompt)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[kite.pending]Cancelled[/]")
            return None

        if not raw or raw.lower() in {"q", "quit"}:
            console.print("[kite.pending]Cancelled[/]")
            return None

        if refreshable and raw.lower() in {"r", "refresh"}:
            return REFRESH_PICK

        key = raw.lower()
        if key in _PAGE_NEXT:
            if extra_after:
                offset += show
            continue
        if key in _PAGE_PREV:
            offset = max(0, offset - show)
            continue

        ids = {item_id: item_id for item_id, _ in pool}
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(shown):
                return shown[idx - 1][0]
            if 1 <= idx <= len(pool):
                return pool[idx - 1][0]
            console.print("[kite.pending]Number out of range — try a filter or +/−[/]")
            continue
        if raw in ids:
            return raw
        needle = raw.lower()
        hits = [
            (item_id, label)
            for item_id, label in pool
            if needle in item_id.lower() or needle in label.lower()
        ]
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1:
            return hits[0][0]
        if len(hits) > 1:
            pool = hits
            offset = 0
            continue
        console.print(f"[kite.pending]No matching {noun}[/]  — type part of the id")
        pool = list(items)
        offset = 0


def confirm(console: Console, question: str, *, default: bool = True) -> bool:
    """Y/n prompt. Empty uses default. Cancel / EOF → False."""
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        raw = _read_choice(console, f"{question}{suffix}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[kite.pending]Cancelled[/]")
        return False
    if not raw:
        return default
    if raw in {"y", "yes"}:
        return True
    if raw in {"n", "no", "q", "quit"}:
        return False
    return default
