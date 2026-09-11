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
from kite.ui.theme import brand_fg, glyph, pt_style_dict, ui_colors

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

    kind: str  # text | stop | steer | eof | empty | slash | approval | busy_slash
    text: str = ""


# Slash commands safe to run while a turn is in flight (read-only / status / mode).
BUSY_SAFE_SLASHES = frozenset(
    {"tasks", "task", "status", "help", "jobs", "agents", "h", "?", "approve"}
)

_APPROVAL_CHOICES = {
    "a": "allow",
    "s": "session",
    "p": "always",
    "n": "deny",
    "q": "stop",
}


def is_busy_safe_slash(line: str) -> bool:
    raw = (line or "").strip().lower()
    if not raw.startswith("/"):
        return False
    cmd = raw[1:].split()[0].split("@")[0]
    return cmd in BUSY_SAFE_SLASHES


def parse_approval_choice(text: str, *, mandatory: bool) -> str | None:
    """Map composer input to an approval decision key, or None."""
    choice = (text or "").strip().lower()
    if not choice or choice not in _APPROVAL_CHOICES:
        return None
    if mandatory and choice in {"s", "p"}:
        return None
    return _APPROVAL_CHOICES[choice]


def classify_busy_line(line: str) -> ComposerResult:
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
        if is_busy_safe_slash(text):
            return ComposerResult("busy_slash", text)
        return ComposerResult("slash", text)
    return ComposerResult("text", text)


@dataclass(frozen=True)
class BusyComposerHandlers:
    on_queue: Callable[[str], None]
    on_stop: Callable[[], None]
    on_steer: Callable[[str], None]
    on_slash_while_busy: Callable[[], None]
    on_busy_slash: Callable[[str], None] | None = None
    on_approval: Callable[[str], None] | None = None
    on_eof: Callable[[], None] | None = None
    on_empty: Callable[[], None] | None = None
    on_dequeue: Callable[[], None] | None = None


def dispatch_classified_busy(result: ComposerResult, handlers: BusyComposerHandlers) -> bool:
    if result.kind == "eof":
        if handlers.on_eof is not None:
            handlers.on_eof()
        handlers.on_stop()
        return True
    if result.kind == "stop":
        handlers.on_stop()
        return True
    if result.kind == "steer":
        handlers.on_steer(result.text)
        handlers.on_stop()
        return True
    if result.kind == "approval" and handlers.on_approval is not None:
        handlers.on_approval(result.text)
        return False
    if result.kind == "busy_slash" and handlers.on_busy_slash is not None:
        handlers.on_busy_slash(result.text)
        return False
    if result.kind == "slash":
        handlers.on_slash_while_busy()
        return False
    if result.kind == "text":
        handlers.on_queue(result.text)
        return False
    if result.kind == "dequeue":
        if handlers.on_dequeue is not None:
            handlers.on_dequeue()
        return False
    if result.kind == "empty":
        if handlers.on_empty is not None:
            handlers.on_empty()
        else:
            handlers.on_slash_while_busy()
        return False
    return False


def apply_busy_composer_result(result: ComposerResult, handlers: BusyComposerHandlers) -> bool:
    if result.kind == "eof":
        if handlers.on_eof is not None:
            handlers.on_eof()
        handlers.on_stop()
        return True
    if result.kind in {"stop", "steer", "approval", "busy_slash", "empty", "dequeue"}:
        return dispatch_classified_busy(result, handlers)
    if result.kind == "text":
        return dispatch_classified_busy(classify_busy_line(result.text), handlers)
    return False


def apply_busy_text_line(line: str, handlers: BusyComposerHandlers) -> bool:
    return dispatch_classified_busy(classify_busy_line(line), handlers)


def prompt_style() -> Any:
    if not _PT:
        return None
    return Style.from_dict(pt_style_dict())


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
        self._index_cache: CommandIndex | None = None
        self._support_cache: ReasoningSupport | None = None

    def _index(self) -> CommandIndex:
        if self._index_cache is None:
            self._index_cache = self._index_factory()
        return self._index_cache

    def invalidate(self) -> None:
        self._index_cache = None
        self._support_cache = None

    def _support(self) -> ReasoningSupport:
        if self._support_cache is not None:
            return self._support_cache
        if self._reasoning_info is not None:
            try:
                info = self._reasoning_info()
                if info is not None:
                    self._support_cache = info
                    return info
            except Exception:
                pass
        self._support_cache = ReasoningSupport(False, False, False, False, source="none")
        return self._support_cache

    def get_completions(self, document: Any, complete_event: Any):  # noqa: ANN401
        if not _PT:
            return
        raw = document.text_before_cursor
        attach = _at_attach_prefix(raw)
        if attach is not None:
            prefix, start = attach
            yield from _path_completions(prefix, start)
            return
        if not raw.startswith("/"):
            return
        if raw.startswith("//"):
            return

        body = raw[1:]
        cmd, sep, rest = body.partition(" ")
        index = self._index()
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
        elif cmd == "working":
            choices = [("add", "append a soft rhythm signal")]
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
        elif cmd == "goal":
            choices = list(ARG_CHOICES.get("goal", []))
        elif cmd == "agents":
            from kite.agent.subagent_profiles import list_profiles

            bits = rest.split()
            first = bits[0].lower() if bits else ""
            if first in {"", "profiles", "personas", "list", "show", "init", "reload"} or not bits:
                choices.extend(ARG_CHOICES.get("agents", []))
            if first in {"show", "init"} or (first and first not in {"profiles", "personas", "list", "reload"}):
                for prof in list_profiles():
                    mark = f"{glyph('home')}  " if not prof.bundled else ""
                    choices.append((prof.id, f"{mark}{prof.label}  role={prof.role}"[:60]))
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
    return HTML(f"<style fg='{brand_fg()}'><b>{_escape_html(label)}</b></style>")


def _session_rows() -> list[tuple[str, str]]:
    from kite.memory.session import list_sessions
    from kite.memory.session_format import format_session_picker_label

    return [(meta.id, format_session_picker_label(meta)[:72]) for meta in list_sessions(limit=30)]


def _at_attach_prefix(raw: str) -> tuple[str, int] | None:
    """Path prefix after a word-boundary @ (not email addresses)."""
    for i in range(len(raw) - 1, -1, -1):
        if raw[i] != "@":
            continue
        if i > 0 and not raw[i - 1].isspace():
            continue
        prefix = raw[i + 1 :]
        if " " in prefix:
            return None
        return prefix, -(len(prefix) if prefix else 0)
    return None


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
    from kite.ui.commands import LEGACY_ALIASES, is_primary_slash

    rows: list[SlashSpec] = []
    seen: set[str] = set()
    for spec in index.specs.values():
        if spec.name in seen:
            continue
        if spec.name in LEGACY_ALIASES:
            continue
        if spec.kind == "control" and not is_primary_slash(spec.name):
            continue
        if spec.kind == "prompt":
            continue
        if spec.name in {"thinking", "fast"} and not support.can_both:
            continue
        if spec.name in {"reasoning", "effort"} and not support.supported:
            continue
        if ":" in spec.name and spec.source == "skill":
            continue
        seen.add(spec.name)
        rows.append(spec)
    rows.sort(key=lambda s: s.name)
    return rows


def _toolbar_approval_bits(state: SessionUiState) -> list[str]:
    if state.awaiting_approval_mandatory:
        return ["[a] once", "[n] deny", "[q] stop", "mandatory"]
    return ["[a] once", "[s] session", "[p] always", "[n] deny", "[q] stop"]


def _toolbar_busy_bits(state: SessionUiState) -> list[str]:
    bits = ["Esc/Ctrl+C stop", "Enter queue", "Ctrl+G steer", "Ctrl+U dequeue", "F8 attach clip"]
    if state.queue_steer:
        bits.append(f"steer {state.queue_steer}")
    if state.queue_follow:
        bits.append(f"follow-up {state.queue_follow}")
    elif state.queued:
        bits.append(f"queued {state.queued}")
    head = (state.queue_head or "").strip()
    if head:
        kind = "steer" if state.queue_head_kind == "steer" else "follow-up"
        if len(head) > 36:
            head = head[:33] + "…"
        bits.append(f"next {kind}: {head}")
    if state.compacting:
        bits.append("compacting")
    if state.budget_limit is not None and state.budget_limit > 0:
        bits.append(f"budget ≤${state.budget_limit:.2f}")
    if state.live_terminal:
        bits.append("live")
    if state.live_subagents:
        bits.append("live-agents")
    bits.append("/tasks")
    return bits


def _toolbar_hint_line(bits: list[str]) -> str:
    if not bits:
        return ""
    return f"  {glyph('sep')} " + f"  {glyph('sep')} ".join(bits)


def _toolbar_html(state: SessionUiState) -> Any:
    ui = ui_colors()
    if state.awaiting_approval:
        hints = _toolbar_hint_line(_toolbar_approval_bits(state))
        return HTML(f"<style fg='{ui.accent}'>{_escape_html(hints.strip())}</style>")

    tail = format_status_tail(state)
    flash = ""
    if state.flash:
        flash = (
            f"  {glyph('sep')} <style fg='{ui.accent}'><b>{_escape_html(state.flash)}</b></style>"
        )
    hints = _toolbar_hint_line(_toolbar_busy_bits(state)) if state.busy else ""
    main = (
        f"<style fg='{brand_fg()}'><b>kite</b></style>"
        f"<style fg='{ui.muted}'> {glyph('sep')} {_escape_html(tail)}{flash}{hints}</style>"
    )
    lines: list[str] = []
    if state.busy:
        running = format_running_status(state)
        if running:
            lines.append(
                f"<style fg='{ui.accent}'>●</style>"
                f"<style fg='{ui.muted}'> {_escape_html(running)}</style>"
            )
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
    on_attach_clipboard: Callable[[], str] | None = None,
    on_clear_screen: Callable[[], None] | None = None,
    on_toggle_fullscreen: Callable[[], str] | None = None,
    is_busy: Callable[[], bool] | None = None,
    is_awaiting_approval: Callable[[], bool] | None = None,
    can_remember_approval: Callable[[], bool] | None = None,
    action_slot: dict[str, str] | None = None,
) -> Any:
    """Keyboard shortcuts while the composer is focused."""
    if not _PT:
        return None
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()
    slot = action_slot if action_slot is not None else {}

    def _busy() -> bool:
        return bool(is_busy and is_busy())

    def _awaiting_approval() -> bool:
        return bool(is_awaiting_approval and is_awaiting_approval())

    def _can_remember() -> bool:
        return bool(can_remember_approval and can_remember_approval())

    busy = Condition(_busy)
    awaiting = Condition(_awaiting_approval)

    def _approval_hotkeys_ready() -> bool:
        """Single-letter a/n/q/s/p only when composer is empty (else type normally)."""
        if not _awaiting_approval():
            return False
        try:
            from prompt_toolkit.application.current import get_app

            text = get_app().current_buffer.text or ""
            return not text.strip()
        except Exception:
            return True

    approval_hotkey = Condition(_approval_hotkeys_ready)
    remember_hotkey = Condition(lambda: _can_remember() and _approval_hotkeys_ready())

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

    @bindings.add("c-space", eager=True)
    def _fullscreen(event) -> None:  # noqa: ANN001
        _fire(on_toggle_fullscreen, event)

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

    @bindings.add("c-u", eager=True, filter=busy)
    def _dequeue(event) -> None:  # noqa: ANN001
        slot["kind"] = "dequeue"
        event.app.exit(result="")

    for key in ("a", "n", "q"):
        @bindings.add(key, eager=True, filter=approval_hotkey)
        def _approval_key(event, *, _key=key) -> None:  # noqa: ANN001
            slot["kind"] = "approval"
            event.app.exit(result=_key)

    for key in ("s", "p"):
        @bindings.add(key, eager=True, filter=remember_hotkey)
        def _approval_remember(event, *, _key=key) -> None:  # noqa: ANN001
            slot["kind"] = "approval"
            event.app.exit(result=_key)

    @bindings.add("enter", eager=True, filter=awaiting)
    def _approval_enter(event) -> None:  # noqa: ANN001
        """Approval requires an explicit key; empty Enter keeps waiting."""
        buf = event.current_buffer
        buf.complete_state = None
        text = (buf.text or "").strip().lower()
        if not text:
            event.app.invalidate()
            return
        buf.validate_and_handle()

    not_awaiting = Condition(lambda: not _awaiting_approval())

    @bindings.add("enter", eager=True, filter=not_awaiting)
    def _submit(event) -> None:  # noqa: ANN001
        # complete_while_typing keeps an invisible menu open; default Enter
        # then "accepts" the completion instead of sending the line.
        # prompt_toolkit stores this as c-m (ControlM).
        buf = event.current_buffer
        buf.complete_state = None
        buf.validate_and_handle()

    @bindings.add("tab", eager=True)
    def _tab_cycle(event) -> None:  # noqa: ANN001
        """Tab cycles slash/@ completions; Enter always sends the line."""
        buf = event.current_buffer
        if buf.complete_state is not None:
            buf.complete_next()
            return
        text = buf.text
        if text.startswith("/") or _at_attach_prefix(buf.document.text_before_cursor) is not None:
            buf.start_completion(select_first=False)

    @bindings.add("c-l", eager=True)
    def _clear_screen(event) -> None:  # noqa: ANN001
        if on_clear_screen:
            on_clear_screen()
        else:
            try:
                event.app.renderer.clear()
            except Exception:
                pass
        event.app.invalidate()

    def _paste_system_clipboard(event) -> None:  # noqa: ANN001
        """Ctrl+V / Shift+Insert — paste OS clipboard into the composer."""
        from kite.ui.attach import read_os_clipboard

        text = read_os_clipboard()
        if not text:
            return
        buf = event.current_buffer
        buf.cut_selection()
        buf.insert_text(text.replace("\r\n", "\n").replace("\r", "\n"))

    def _copy_selection(event) -> None:  # noqa: ANN001
        """Ctrl+Insert — copy composer selection to OS clipboard."""
        from kite.ui.attach import write_os_clipboard

        buf = event.current_buffer
        data = buf.copy_selection()
        if data is None:
            return
        text = data.text if hasattr(data, "text") else str(data)
        if text:
            write_os_clipboard(text)

    @bindings.add("f8", eager=True)
    @bindings.add("escape", "v", eager=True)
    def _attach_clipboard(event) -> None:  # noqa: ANN001
        """F8 or Esc v — attach clipboard to the next turn (/clip)."""
        if on_attach_clipboard:
            note = on_attach_clipboard()
            if note:
                slot["kind"] = "note"
        event.app.invalidate()

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
    prefill: str = "",
) -> ComposerResult:
    ui = ui_colors()
    if state.awaiting_approval:
        if state.awaiting_approval_mandatory:
            placeholder = "[a] once · [n] deny · [q] stop — approval required"
        else:
            placeholder = "[a] once · [s] session · [p] always · [n] deny · [q] stop"
    elif busy:
        placeholder = "add a follow-up while Kite works…"
    else:
        placeholder = "/ · @file · Ctrl+V paste · F8 attach clip · Ctrl+D quit · /help"

    def _toolbar() -> Any:
        if on_poll is not None:
            on_poll()
        return _toolbar_html(state)

    try:
        if prefill:
            session.default_buffer.text = prefill
        text = session.prompt(
            HTML(f"<style fg='{brand_fg()}'>{glyph('prompt')}</style> "),
            placeholder=HTML(f"<style fg='{ui.placeholder}'>{placeholder}</style>"),
            bottom_toolbar=_toolbar,
            refresh_interval=0.25 if (busy or state.awaiting_approval) else 0,
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
    if kind == "approval":
        decision = parse_approval_choice(text, mandatory=state.awaiting_approval_mandatory) or "deny"
        return ComposerResult("approval", decision)
    if kind == "stop":
        return ComposerResult("stop")
    if kind == "steer":
        return ComposerResult("steer", text)
    if kind == "dequeue":
        return ComposerResult("dequeue")
    if state.awaiting_approval:
        decision = parse_approval_choice(text, mandatory=state.awaiting_approval_mandatory)
        if decision:
            return ComposerResult("approval", decision)
        # Wake/poll exits the composer with empty text while awaiting — must
        # not treat that as deny (users never pressed n).
        if not text:
            return ComposerResult("empty")
    if not text:
        return ComposerResult("empty")
    if busy and is_busy_safe_slash(text):
        return ComposerResult("busy_slash", text)
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
    on_busy_slash: Callable[[str], None] | None = None,
    on_approval: Callable[[str], None] | None = None,
    on_eof: Callable[[], None],
    on_empty: Callable[[], None] | None = None,
    on_dequeue: Callable[[], str] | None = None,
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
            prefill_ref: list[str] = [""]

            def _handle_dequeue() -> None:
                if on_dequeue is not None:
                    prefill_ref[0] = on_dequeue()

            while should_continue():
                if on_tick is not None:
                    on_tick()
                action_slot["kind"] = "submit"
                prefill = prefill_ref[0]
                prefill_ref[0] = ""
                result = _prompt_once(
                    session,
                    state,
                    busy=True,
                    action_slot=action_slot,
                    on_poll=on_poll or on_tick,
                    prefill=prefill,
                )
                if not should_continue():
                    break
                handlers = BusyComposerHandlers(
                    on_queue=on_queue,
                    on_stop=on_stop,
                    on_steer=on_steer,
                    on_slash_while_busy=on_slash_while_busy,
                    on_busy_slash=on_busy_slash,
                    on_approval=on_approval,
                    on_eof=on_eof,
                    on_empty=on_empty,
                    on_dequeue=_handle_dequeue if on_dequeue else None,
                )
                if apply_busy_composer_result(result, handlers):
                    break
                if result.kind == "empty" and on_tick is not None:
                    on_tick()
    finally:
        state._refresh = None
