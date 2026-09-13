"""Numbered pickers — typed input plus a raw-key list (arrows / wheel)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

_PICK_SHOW = 40
REFRESH_PICK = "__refresh__"

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

    paint()
    reader = _event_reader()
    try:
        while True:
            ev = reader()
            if ev is None:
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


def _event_reader():
    if sys.platform == "win32":
        return _WinEvents()
    return _PosixEvents()


class _WinEvents:
    """Windows keys via msvcrt — does not take over the console (PT Application did)."""

    def __init__(self) -> None:
        import msvcrt

        self._msvcrt = msvcrt

    def __call__(self) -> str | None:
        ch = self._msvcrt.getwch()
        if ch in {"\x00", "\xe0"}:
            code = self._msvcrt.getwch()
            return {
                "H": "up",
                "P": "down",
                "I": "pageup",
                "Q": "pagedown",
                "G": "home",
                "O": "end",
            }.get(code)
        if ch in {"\r", "\n"}:
            return "enter"
        if ch in {"\x1b", "\x03"}:
            return "esc" if ch == "\x1b" else "ctrl-c"
        if ch == "\x08":
            return "backspace"
        if ch == "\x12":
            return "refresh"
        return ch if ch.isprintable() else None

    def close(self) -> None:
        return None


class _PosixEvents:
    def __init__(self) -> None:
        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._termios = termios
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        sys.stderr.write("\x1b[?1000h\x1b[?1006h")
        sys.stderr.flush()
        self._closed = False
        self._buf = ""

    def __call__(self) -> str | None:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        if not ready:
            return None
        chunk = sys.stdin.read(1)
        if not chunk:
            return "esc"
        if chunk == "\x1b":
            rest = ""
            if select.select([sys.stdin], [], [], 0.02)[0]:
                rest = sys.stdin.read(1)
                if rest == "[" and select.select([sys.stdin], [], [], 0.02)[0]:
                    rest += sys.stdin.read(1)
                    while rest[-1].isdigit() or rest[-1] in ";<":
                        if not select.select([sys.stdin], [], [], 0.02)[0]:
                            break
                        rest += sys.stdin.read(1)
            seq = chunk + rest
            return {
                "\x1b[A": "up",
                "\x1b[B": "down",
                "\x1b[5~": "pageup",
                "\x1b[6~": "pagedown",
                "\x1b[H": "home",
                "\x1b[F": "end",
                "\x1b": "esc",
            }.get(seq) or _posix_mouse(seq)
        if chunk in "\r\n":
            return "enter"
        if chunk == "\x03":
            return "ctrl-c"
        if chunk in "\x7f\x08":
            return "backspace"
        if chunk == "\x12":
            return "refresh"
        return chunk if chunk.isprintable() else None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            sys.stderr.write("\x1b[?1006l\x1b[?1000l")
            sys.stderr.flush()
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old)
        except Exception:
            pass


def _posix_mouse(seq: str) -> str | None:
    # SGR: ESC [ < btn ; x ; y M/m
    if not seq.startswith("\x1b[<") or len(seq) < 6:
        return None
    end = seq[-1]
    try:
        btn, _x, _y = seq[3:-1].split(";")
        code = int(btn)
    except ValueError:
        return None
    if code & 64:
        return "down" if code & 1 else "up"
    if end == "M" and (code & 3) == 0:
        return "enter"
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
