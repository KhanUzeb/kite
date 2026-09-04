"""Slash-command dropdown — name + one-line description, nested args."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kite.cli.slash import CommandIndex, SlashSpec
from kite.config import ensure_home, kite_home
from kite.models.reasoning import ReasoningSupport
from kite.ui.attach import IMAGE_EXTS
from kite.ui.commands import ALIASES, ARG_CHOICES
from kite.ui.state import SessionUiState
from kite.ui.status import format_metrics_tail, format_running_status, format_status_tail
from kite.ui.theme import brand_ansi, glyph, is_dark

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.shortcuts import CompleteStyle
    from prompt_toolkit.styles import Style

    _PT = True
except Exception:  # pragma: no cover
    Completer = object  # type: ignore[misc, assignment]
    Completion = object  # type: ignore[misc, assignment]
    PromptSession = None  # type: ignore[misc, assignment]
    CompleteStyle = None  # type: ignore[misc, assignment]
    _PT = False


@dataclass(frozen=True)
class ComposerResult:
    """One composer submission. `eof` leaves the REPL; empty text is a no-op."""

    kind: str  # text | stop | steer | eof | empty | slash
    text: str = ""


def classify_busy_line(line: str) -> ComposerResult:
    """Map composer text entered while a turn is running."""
    text = (line or "").strip()
    if not text:
        return ComposerResult("empty")
    low = text.lower()
    if low in {"/stop", "/s"}:
        return ComposerResult("stop")
    if low in {"/quit", "/q", "/exit"}:
        return ComposerResult("eof")
    if low.startswith("/steer "):
        return ComposerResult("steer", text.split(" ", 1)[1])
    if text.startswith("/"):
        return ComposerResult("slash", text)
    return ComposerResult("text", text)


def _pt_style(*, dark: bool) -> Any:
    if not _PT:
        return None
    if dark:
        return Style.from_dict(
            {
                "prompt": "ansibrightcyan bold",
                "placeholder": "#4a4a4a",
                "bottom-toolbar": "noreverse #5c5c5c bg:#050505",
                "completion-menu": "bg:#050505 #b8b8b8",
                "completion-menu.completion": "bg:#050505 #b8b8b8",
                "completion-menu.completion.current": "bg:#003333 #a8ffff bold",
                "completion-menu.meta.completion": "#555555",
                "completion-menu.meta.completion.current": "#7a9a9a",
                "completion-menu.multi-column-meta": "bg:#0a0a0a #555555",
                "scrollbar.background": "bg:#0a0a0a",
                "scrollbar.button": "bg:#2a2a2a",
                "auto-suggestion": "#3a3a3a",
            }
        )
    return Style.from_dict(
        {
            "prompt": "ansiblue bold",
            "placeholder": "#888888",
            "bottom-toolbar": "noreverse #555555 bg:#f0f0f0",
            "completion-menu": "bg:#ffffff #222222",
            "completion-menu.completion": "bg:#ffffff #222222",
            "completion-menu.completion.current": "bg:#d6ebff #000000 bold",
            "completion-menu.meta.completion": "#777777",
            "completion-menu.meta.completion.current": "#444444",
            "completion-menu.multi-column-meta": "bg:#f4f4f4 #777777",
            "scrollbar.background": "bg:#eeeeee",
            "scrollbar.button": "bg:#cccccc",
            "auto-suggestion": "#aaaaaa",
        }
    )


def prompt_style() -> Any:
    return _pt_style(dark=is_dark())


_LEVEL_META = {
    "on": "this API has no extra levels",
    "minimal": "least thinking",
    "min": "low latency",
    "low": "low effort / low latency",
    "medium": "balanced",
    "high": "extended thinking",
    "xhigh": "max thinking",
    "max": "max thinking",
}


def effort_menu(support: ReasoningSupport, mode: str) -> list[tuple[str, str]]:
    return [(level, _LEVEL_META.get(level.lower(), f"{mode} level")) for level in support.levels_for(mode)]


class SlashCompleter(Completer):  # type: ignore[misc]
    """When the line starts with `/`, offer builtins, commands, skills, plugins."""

    def __init__(
        self,
        index_factory: Callable[[], CommandIndex],
        *,
        models_factory: Callable[[], Iterable[str]] | None = None,
        providers_factory: Callable[[], Iterable[str]] | None = None,
        reasoning_info: Callable[[], ReasoningSupport | None] | None = None,
    ) -> None:
        self._index_factory = index_factory
        self._models_factory = models_factory or (lambda: ())
        self._providers_factory = providers_factory or (lambda: ())
        self._reasoning_info = reasoning_info

    def _support(self) -> ReasoningSupport:
        if self._reasoning_info is not None:
            try:
                info = self._reasoning_info()
                if info is not None:
                    return info
            except Exception:
                pass
        return ReasoningSupport(False, False, False, False, source="none")

    def get_completions(self, document: Any, complete_event: Any):  # noqa: ANN401
        if not _PT:
            return
        raw = document.text_before_cursor
        if not raw.startswith("/"):
            return
        if raw.startswith("//"):
            return

        body = raw[1:]
        cmd, sep, rest = body.partition(" ")
        index = self._index_factory()
        support = self._support()

        if not sep:
            prefix = cmd.lower()
            seen: set[str] = set()
            for spec in _visible_specs(index, support=support):
                name = spec.name
                if name in seen:
                    continue
                if prefix and not (name.startswith(prefix) or prefix in name):
                    continue
                seen.add(name)
                meta = (spec.description or spec.source or "").strip()
                if spec.hint:
                    meta = f"{spec.hint}  {meta}".strip()
                if spec.name in {"thinking", "fast"}:
                    levels = " ".join(support.levels_for(spec.name))
                    if levels:
                        meta = f"{levels}  {meta}".strip()
                yield Completion(
                    spec.name,
                    start_position=-len(cmd),
                    display=_slash_completion_display(spec, index),
                    display_meta=meta[:72],
                )
            return

        name = ALIASES.get(cmd.lower(), cmd.lower())
        from kite.ui.commands import LEGACY_ALIASES

        if name in LEGACY_ALIASES:
            name = LEGACY_ALIASES[name]
        yield from self._arg_completions(name, rest, index, legacy_cmd=cmd.lower())

    def _arg_completions(self, cmd: str, rest: str, index: CommandIndex, *, legacy_cmd: str = ""):
        token = rest
        # only complete the last token
        prefix = token.split()[-1] if token and not token.endswith(" ") else ""
        start = -len(prefix) if prefix else 0
        choices: list[tuple[str, str]] = []
        routed = legacy_cmd or cmd

        if routed in {"thinking", "fast"}:
            choices = effort_menu(self._support(), routed)
        elif cmd == "model" or routed in {"models", "select", "provider", "refresh"}:
            yield from self._model_arg_completions(cmd, rest, routed=routed)
            return
        elif cmd in ARG_CHOICES:
            choices = list(ARG_CHOICES[cmd])
        elif cmd in {"login", "logout", "signin", "signout"}:
            from kite.providers.credentials import loginable_providers

            for name, display, env in loginable_providers():
                choices.append((name, f"{env}  {display[:40]}"))
        elif cmd in {"skills", "skill"}:
            bits = rest.split()
            first = bits[0].lower() if bits else ""
            if first not in {"add", "install"}:
                choices.append(("add", "install from npm, npx, or GitHub"))
                for skill in index.skills:
                    mark = f"{glyph('home')}  " if skill.source == "user" else ""
                    choices.append((skill.name, f"{mark}{(skill.description or '')[:56]}".strip()))
        elif cmd in {"plugins", "plugin"}:
            choices.append(("init", "scaffold .kite/plugins/name"))
            for plugin in index.plugins:
                choices.append((plugin.name, (plugin.description or plugin.source)[:60]))
        elif cmd == "commands":
            choices.append(("new", "write .kite/commands/name.md"))
        elif cmd == "memory":
            choices = [("semantic", "markdown facts"), ("episodic", "sqlite log")]
        elif cmd == "attach":
            yield from _path_completions(prefix, start)
            return
        elif cmd == "detach":
            choices = [("all", "drop pending attachments")]
        elif cmd in {"session", "sessions", "resume"}:
            bits = rest.split()
            first = bits[0].lower() if bits else ""
            verbs = {
                "list": "recent transcripts",
                "show": "print a transcript",
                "open": "continue this chat",
                "delete": "remove a session",
            }
            listing = cmd == "resume" or (
                first in {"delete", "open", "show", "resume"}
                and (rest.endswith(" ") or len(bits) > 1)
            )
            if listing:
                if first == "delete":
                    choices.append(("all", "every saved session"))
                choices.extend(_session_rows())
            elif not bits or (len(bits) == 1 and not rest.endswith(" ")):
                choices = list(verbs.items()) + _session_rows()

        needle = prefix.lower()
        for value, meta in choices:
            if needle and needle not in value.lower():
                continue
            yield Completion(value, start_position=start, display=value, display_meta=meta[:60])

    def _models_for(self, provider: str | None = None) -> list[str]:
        try:
            out = self._models_factory(provider)  # type: ignore[call-arg]
        except TypeError:
            out = self._models_factory()
        return [str(m) for m in out]

    def _model_arg_completions(self, cmd: str, rest: str, *, routed: str):
        """Completions for /model, /models, /select, /provider — real model ids, not loops."""
        parts = rest.split()
        trailing = bool(rest) and rest.endswith(" ")
        prefix = parts[-1] if parts and not trailing else ""
        start = -len(prefix) if prefix else 0
        choices: list[tuple[str, str]] = []

        sub = parts[0].lower() if parts else ""
        want_providers = False
        model_provider: str | None = None

        if routed == "select" or (cmd == "model" and sub == "select"):
            want_providers = True
            if sub == "select" and (len(parts) > 1 or trailing):
                # /model select <provider> — still providers only
                pass
        elif routed == "provider" or (cmd == "model" and sub == "provider"):
            want_providers = True
        elif cmd == "model" and sub == "list":
            want_providers = True
        elif routed == "models":
            if not parts or (len(parts) == 1 and not trailing):
                choices.append(("refresh", "re-fetch models from API, then pick"))
                want_providers = True
            elif sub in {"refresh", "r"}:
                want_providers = True
            else:
                model_provider = parts[0]
        elif cmd == "model" and sub == "refresh":
            want_providers = True
        elif cmd == "model":
            # /model <list|select|refresh|id> — verbs + live model ids for current provider
            choices.extend(ARG_CHOICES.get("model", []))
            for mid in self._models_for(None):
                choices.append((mid, "model"))
        elif routed == "refresh":
            want_providers = True
        else:
            for mid in self._models_for(None):
                choices.append((mid, "model"))

        if want_providers:
            for name in self._providers_factory():
                choices.append((name, "provider"))
        elif model_provider is not None:
            for mid in self._models_for(model_provider):
                choices.append((mid, "model"))

        needle = prefix.lower()
        for value, meta in choices:
            if needle and needle not in value.lower():
                continue
            yield Completion(value, start_position=start, display=value, display_meta=meta[:60])


def _slash_display(spec: SlashSpec, index: CommandIndex) -> str:
    mark = ""
    if spec.source == "skill":
        skill = next((s for s in index.skills if s.name.lower() == spec.name), None)
        if skill is not None and skill.source == "user":
            mark = f" {glyph('home')}"
    return f"/{spec.name}{mark}"


def _slash_completion_display(spec: SlashSpec, index: CommandIndex) -> Any:
    """Colored slash label for the dark completion menu."""
    label = _slash_display(spec, index)
    if not _PT:
        return label
    brand = brand_ansi()
    return HTML(f"<style fg='{brand}'><b>{_escape_html(label)}</b></style>")


def _session_rows() -> list[tuple[str, str]]:
    from kite.memory.session import list_sessions

    return [(meta.id, (meta.label or meta.task)[:50]) for meta in list_sessions(limit=30)]


def _path_completions(prefix: str, start: int):
    if not prefix:
        folder, needle = Path("."), ""
    elif prefix.endswith(("/", "\\")):
        folder, needle = Path(prefix), ""
    else:
        path = Path(prefix)
        folder, needle = path.parent, path.name
        if str(folder) in {".", ""}:
            folder = Path(".")
    if not folder.exists() or not folder.is_dir():
        folder = Path(".")
    needle_l = needle.lower()
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return
    shown = 0
    for item in entries:
        if needle_l and needle_l not in item.name.lower():
            continue
        if item.name.startswith(".") and not needle.startswith("."):
            continue
        meta = "image" if item.suffix.lower() in IMAGE_EXTS else ("dir" if item.is_dir() else "file")
        display = item.name + ("/" if item.is_dir() else "")
        yield Completion(str(item), start_position=start, display=display, display_meta=meta)
        shown += 1
        if shown >= 40:
            return


def _visible_specs(index: CommandIndex, *, support: ReasoningSupport) -> list[SlashSpec]:
    rows: list[SlashSpec] = []
    seen: set[str] = set()
    for spec in index.specs.values():
        if spec.name in seen:
            continue
        if spec.name in {"thinking", "fast"} and not support.can_both:
            continue
        if spec.name in {"reasoning", "effort"} and not support.supported:
            continue
        if ":" in spec.name and spec.source == "skill":
            continue
        seen.add(spec.name)
        rows.append(spec)
    rows.sort(key=lambda s: (0 if s.kind == "control" else 1, s.name))
    return rows


def _toolbar_html(state: SessionUiState) -> Any:
    tail = format_status_tail(state)
    brand = brand_ansi()
    muted = "#555555" if is_dark() else "#666666"
    accent = "#c9a227" if is_dark() else "#9a7b0a"
    flash = ""
    if state.flash:
        flash = f"  {glyph('sep')} {_escape_html(state.flash)}"
    hints = ""
    if state.awaiting_approval:
        bits = [f"approve {state.awaiting_approval}", "Esc stop", "Enter queue", "Ctrl+G steer"]
        if state.queued:
            bits.append(f"queued {state.queued}")
        hints = f"  {glyph('sep')} " + f"  {glyph('sep')} ".join(bits)
    elif state.busy:
        bits = ["Esc stop", "Enter queue", "Ctrl+G steer"]
        if state.queued:
            bits.append(f"queued {state.queued}")
        if state.budget_limit is not None and state.budget_limit > 0:
            bits.append(f"budget ≤${state.budget_limit:.2f}")
        bits.append("/tasks")
        hints = f"  {glyph('sep')} " + f"  {glyph('sep')} ".join(bits)
    main = (
        f"<style fg='{brand}'><b>kite</b></style>"
        f"<style fg='{muted}'> {glyph('sep')} {_escape_html(tail)}{flash}{hints}</style>"
    )
    lines: list[str] = []
    running = format_running_status(state)
    if running:
        lines.append(
            f"<style fg='{accent}'>●</style>"
            f"<style fg='{muted}'> {_escape_html(running)}</style>"
        )
    metrics = format_metrics_tail(state)
    if metrics:
        lines.append(f"<style fg='{muted}'>{_escape_html(metrics)}</style>")
    lines.append(main)
    return HTML("\n".join(lines))


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def history_path() -> Path:
    ensure_home()
    return kite_home() / "history"


def _mouse_support_enabled() -> bool:
    """Off by default so the terminal keeps drag-select, copy, and right-click paste.

    Set KITE_MOUSE=1 to capture the mouse for slash-menu wheel scrolling
    (native selection then needs Shift+drag in most terminals).
    """
    import os

    return os.environ.get("KITE_MOUSE", "").strip().lower() in {"1", "true", "yes", "on"}


def make_prompt_session(
    completer: SlashCompleter,
    *,
    key_bindings: Any | None = None,
) -> Any:
    if not _PT:
        return None
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "history": FileHistory(str(path)),
        "completer": completer,
        "complete_while_typing": True,
        "auto_suggest": AutoSuggestFromHistory(),
        "style": prompt_style(),
        # False restores OS/terminal copy-paste, drag-select, and right-click.
        "mouse_support": _mouse_support_enabled(),
        "reserve_space_for_menu": 8,
    }
    if key_bindings is not None:
        kwargs["key_bindings"] = key_bindings
    if CompleteStyle is not None:
        kwargs["complete_style"] = CompleteStyle.COLUMN
    return PromptSession(**kwargs)


def make_repl_key_bindings(
    *,
    on_toggle_expand: Callable[[], str] | None = None,
    on_toggle_thinking: Callable[[], str] | None = None,
    on_expand_thinking: Callable[[], str | None] | None = None,
    on_plan: Callable[[], str] | None = None,
    on_build: Callable[[], str] | None = None,
    on_status: Callable[[], str] | None = None,
    is_busy: Callable[[], bool] | None = None,
    action_slot: dict[str, str] | None = None,
) -> Any:
    """Keyboard shortcuts while the composer is focused.

    Custom bindings use eager=True so they win over emacs Ctrl+P/B/T/O.
    Ctrl+S is not bound — terminals steal it for XOFF; use F2 for status.
    Mouse is off by default (see ``_mouse_support_enabled``) so drag-copy and
    right-click paste stay with the terminal.
    """
    if not _PT:
        return None
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()
    slot = action_slot if action_slot is not None else {}

    def _busy() -> bool:
        return bool(is_busy and is_busy())

    busy = Condition(_busy)

    def _fire(cb: Callable[[], str] | None, event) -> None:  # noqa: ANN001
        if cb:
            cb()
        event.app.invalidate()

    @bindings.add("c-o", eager=True)
    @bindings.add("f6", eager=True)
    def _expand(event) -> None:  # noqa: ANN001
        _fire(on_toggle_expand, event)

    @bindings.add("c-t", eager=True)
    @bindings.add("f7", eager=True)
    def _thinking(event) -> None:  # noqa: ANN001
        _fire(on_toggle_thinking, event)

    @bindings.add("c-p", eager=True)
    @bindings.add("f3", eager=True)
    def _plan(event) -> None:  # noqa: ANN001
        _fire(on_plan, event)

    @bindings.add("c-b", eager=True)
    @bindings.add("f4", eager=True)
    def _build(event) -> None:  # noqa: ANN001
        _fire(on_build, event)

    @bindings.add("f2", eager=True)
    def _status(event) -> None:  # noqa: ANN001
        _fire(on_status, event)

    idle = Condition(lambda: not _busy())

    @bindings.add("f5", eager=True, filter=idle)
    def _refresh_models(event) -> None:  # noqa: ANN001
        slot["kind"] = "submit"
        event.app.exit(result="/refresh")

    @bindings.add("escape", eager=True, filter=busy)
    def _stop(event) -> None:  # noqa: ANN001
        slot["kind"] = "stop"
        event.app.exit(result="")

    @bindings.add("c-g", eager=True, filter=busy)
    def _steer(event) -> None:  # noqa: ANN001
        slot["kind"] = "steer"
        event.app.exit(result=event.current_buffer.text)

    @bindings.add("enter", eager=True)
    def _submit(event) -> None:  # noqa: ANN001
        # complete_while_typing keeps an invisible menu open; default Enter
        # then "accepts" the completion instead of sending the line.
        # prompt_toolkit stores this as c-m (ControlM).
        buf = event.current_buffer
        buf.complete_state = None
        buf.validate_and_handle()

    def _paste_system_clipboard(event) -> None:  # noqa: ANN001
        """Ctrl+V / Shift+Insert — paste OS clipboard into the composer."""
        text = _read_os_clipboard()
        if not text:
            return
        buf = event.current_buffer
        buf.cut_selection()
        buf.insert_text(text.replace("\r\n", "\n").replace("\r", "\n"))

    def _copy_selection(event) -> None:  # noqa: ANN001
        """Ctrl+Insert — copy composer selection to OS clipboard."""
        buf = event.current_buffer
        data = buf.copy_selection()
        if data is None:
            return
        text = data.text if hasattr(data, "text") else str(data)
        if text:
            _write_os_clipboard(text)

    @bindings.add("c-v", eager=True)
    @bindings.add("s-insert", eager=True)
    def _paste(event) -> None:  # noqa: ANN001
        _paste_system_clipboard(event)

    @bindings.add("c-insert", eager=True)
    def _copy(event) -> None:  # noqa: ANN001
        _copy_selection(event)

    # Optional mouse wheel for slash menu when KITE_MOUSE=1
    if _mouse_support_enabled():

        def _scroll_completions(event, *, forward: bool) -> None:  # noqa: ANN001
            buff = event.app.current_buffer
            if buff.complete_state is None:
                return
            if forward:
                buff.complete_next()
            else:
                buff.complete_previous()

        @bindings.add("<scroll-up>")
        def _scroll_up(event) -> None:  # noqa: ANN001
            _scroll_completions(event, forward=False)

        @bindings.add("<scroll-down>")
        def _scroll_down(event) -> None:  # noqa: ANN001
            _scroll_completions(event, forward=True)

        # Double-click expand thinking only when we own the mouse.
        if on_expand_thinking is not None:
            import time

            from prompt_toolkit.keys import Keys
            from prompt_toolkit.mouse_events import MouseButton, MouseEventType

            last_click = {"t": 0.0, "x": -99, "y": -99}

            def _is_double_click(x: int, y: int) -> bool:
                now = time.monotonic()
                hit = (
                    now - float(last_click["t"]) < 0.45
                    and abs(x - int(last_click["x"])) <= 2
                    and abs(y - int(last_click["y"])) <= 2
                )
                last_click["t"] = now
                last_click["x"] = x
                last_click["y"] = y
                return hit

            def _handle_mouse_expand(x: int, y: int, button: Any, event_type: Any, event) -> Any:  # noqa: ANN001
                if _busy():
                    return NotImplemented
                button_s = str(getattr(button, "value", button))
                type_s = str(getattr(event_type, "value", event_type))
                is_left = button in {MouseButton.LEFT, "LEFT"} or button_s.upper() == "LEFT"
                is_down = (
                    event_type in {MouseEventType.MOUSE_DOWN, "MOUSE_DOWN"} or type_s == "MOUSE_DOWN"
                )
                if not (is_left and is_down):
                    return NotImplemented
                if not _is_double_click(x, y):
                    return NotImplemented
                note = on_expand_thinking()
                if note:
                    event.app.invalidate()
                return None

            @bindings.add(Keys.WindowsMouseEvent, eager=True)
            def _win_mouse(event) -> Any:  # noqa: ANN001
                try:
                    button, event_type, x_s, y_s = str(event.data or "").split(";")
                    return _handle_mouse_expand(int(x_s), int(y_s), button, event_type, event)
                except Exception:
                    return NotImplemented

            @bindings.add(Keys.Vt100MouseEvent, eager=True)
            def _vt_mouse(event) -> Any:  # noqa: ANN001
                raw = str(event.data or "")
                try:
                    if not raw.startswith("<") or not raw.endswith("M"):
                        return NotImplemented
                    parts = raw[1:-1].split(";")
                    if len(parts) < 3:
                        return NotImplemented
                    code, x_s, y_s = int(parts[0]), int(parts[1]), int(parts[2])
                    if (code & 3) != 0:
                        return NotImplemented
                    return _handle_mouse_expand(
                        int(x_s) - 1,
                        int(y_s) - 1,
                        MouseButton.LEFT,
                        MouseEventType.MOUSE_DOWN,
                        event,
                    )
                except Exception:
                    return NotImplemented

    return bindings


def _read_os_clipboard() -> str:
    try:
        import sys

        if sys.platform == "win32":
            import ctypes

            CF_UNICODETEXT = 13
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard(0)
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = kernel32.GlobalLock(handle)
                try:
                    return ctypes.wstring_at(ptr) if ptr else ""
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
    except Exception:
        pass
    try:
        import subprocess

        for cmd in (
            ["pbpaste"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["wl-paste", "-n"],
        ):
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2)
                return out.decode("utf-8", errors="replace")
            except (FileNotFoundError, subprocess.SubprocessError, OSError):
                continue
    except Exception:
        pass
    return ""


def _write_os_clipboard(text: str) -> None:
    try:
        import sys

        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            user32.OpenClipboard(0)
            try:
                user32.EmptyClipboard()
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
                ptr = kernel32.GlobalLock(handle)
                ctypes.memmove(ptr, encoded, len(encoded))
                kernel32.GlobalUnlock(handle)
                user32.SetClipboardData(CF_UNICODETEXT, handle)
            finally:
                user32.CloseClipboard()
            return
    except Exception:
        pass
    try:
        import subprocess

        for cmd in (
            ["pbcopy"],
            ["xclip", "-selection", "clipboard"],
            ["wl-copy"],
        ):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=2)
                return
            except (FileNotFoundError, subprocess.SubprocessError, OSError):
                continue
    except Exception:
        pass


def read_repl_line(
    *,
    session: Any,
    state: SessionUiState,
    fallback: Callable[[], str | None],
    busy: bool = False,
    action_slot: dict[str, str] | None = None,
    patch_stdout_ctx: bool = True,
) -> ComposerResult:
    """prompt_toolkit input with `/` dropdown; Rich Prompt if unavailable."""
    if session is None:
        raw = fallback()
        if raw is None:
            return ComposerResult("eof")
        text = raw.strip()
        if not text:
            return ComposerResult("empty")
        return ComposerResult("text", text)

    slot = action_slot if action_slot is not None else {}
    slot["kind"] = "submit"

    def _invalidate() -> None:
        try:
            app = getattr(session, "app", None)
            if app is not None:
                app.invalidate()
        except Exception:
            pass

    state._refresh = _invalidate
    try:
        if patch_stdout_ctx:
            from prompt_toolkit.patch_stdout import patch_stdout

            with patch_stdout(raw=True):
                return _prompt_once(session, state, busy=busy, action_slot=slot)
        return _prompt_once(session, state, busy=busy, action_slot=slot)
    finally:
        state._refresh = None


def _prompt_once(
    session: Any,
    state: SessionUiState,
    *,
    busy: bool,
    action_slot: dict[str, str],
    on_poll: Callable[[], None] | None = None,
) -> ComposerResult:
    placeholder_fg = "#888888" if not is_dark() else "#555555"
    brand = brand_ansi()
    placeholder = "add a follow-up while Kite works…" if busy else "/ commands · @file attach · Ctrl+D quit"

    def _toolbar() -> Any:
        if on_poll is not None:
            on_poll()
        return _toolbar_html(state)

    try:
        text = session.prompt(
            HTML(f"<style fg='{brand}'>{glyph('prompt')}</style> "),
            placeholder=HTML(f"<style fg='{placeholder_fg}'>{placeholder}</style>"),
            bottom_toolbar=_toolbar,
            refresh_interval=0.25 if busy else 0,
        )
    except EOFError:
        return ComposerResult("eof")
    except KeyboardInterrupt:
        typed = ""
        try:
            typed = str(session.default_buffer.text or "").strip()
        except Exception:
            typed = ""
        if busy:
            if typed:
                return ComposerResult("steer", typed)
            return ComposerResult("stop")
        return ComposerResult("empty")

    kind = action_slot.get("kind") or "submit"
    text = (text or "").strip()
    if kind == "stop":
        return ComposerResult("stop")
    if kind == "steer":
        return ComposerResult("steer", text)
    if not text:
        return ComposerResult("empty")
    return ComposerResult("text", text)


def read_repl_busy_composer(
    *,
    session: Any,
    state: SessionUiState,
    action_slot: dict[str, str],
    should_continue: Callable[[], bool],
    on_queue: Callable[[str], None],
    on_stop: Callable[[], None],
    on_steer: Callable[[str], None],
    on_slash_while_busy: Callable[[], None],
    on_eof: Callable[[], None],
    on_tick: Callable[[], None] | None = None,
    on_poll: Callable[[], None] | None = None,
) -> None:
    """Keep the composer pinned while a turn runs — one stdout patch for the whole turn."""
    if session is None:
        return

    def _invalidate() -> None:
        try:
            app = getattr(session, "app", None)
            if app is not None:
                app.invalidate()
        except Exception:
            pass

    state._refresh = _invalidate
    try:
        from prompt_toolkit.patch_stdout import patch_stdout

        with patch_stdout(raw=True):
            while should_continue():
                if on_tick is not None:
                    on_tick()
                action_slot["kind"] = "submit"
                result = _prompt_once(
                    session,
                    state,
                    busy=True,
                    action_slot=action_slot,
                    on_poll=on_poll or on_tick,
                )
                if not should_continue():
                    break
                if result.kind == "eof":
                    on_eof()
                    break
                if result.kind == "stop":
                    on_stop()
                    break
                if result.kind == "steer":
                    on_steer(result.text)
                    on_stop()
                    break
                if result.kind == "empty":
                    if on_tick is not None:
                        on_tick()
                    continue
                line = result.text
                classified = classify_busy_line(line)
                if classified.kind == "stop":
                    on_stop()
                    break
                if classified.kind == "eof":
                    on_eof()
                    on_stop()
                    break
                if classified.kind == "steer":
                    on_steer(classified.text)
                    on_stop()
                    break
                if classified.kind == "slash":
                    on_slash_while_busy()
                    continue
                on_queue(line)
    finally:
        state._refresh = None
