"""Slash-command dropdown — name + one-line description, nested args."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from kite.cli.slash import CommandIndex, SlashSpec
from kite.config import ensure_home, kite_home
from kite.ui.attach import IMAGE_EXTS
from kite.models.reasoning import ReasoningSupport
from kite.ui.commands import ALIASES, ARG_CHOICES
from kite.ui.status import format_status_tail
from kite.ui.theme import brand_ansi, glyph, is_dark
from kite.ui.state import SessionUiState

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


def _pt_style(*, dark: bool) -> Any:
    if not _PT:
        return None
    return Style.from_dict(
        {
            "prompt": "ansicyan" if dark else "ansiblue",
            "placeholder": "#5a5a5a" if dark else "#888888",
            "bottom-toolbar": "noreverse #6e6e6e bg:#121212" if dark else "noreverse #555555 bg:#f4f4f4",
            "completion-menu": "bg:#141414 #c8c8c8" if dark else "bg:#ffffff #222222",
            "completion-menu.completion": "bg:#141414 #c8c8c8" if dark else "bg:#ffffff #222222",
            "completion-menu.completion.current": "bg:#1a2e2e #e8ffff" if dark else "bg:#e0f0ff #000000",
            "completion-menu.meta.completion": "#6e6e6e" if dark else "#777777",
            "completion-menu.meta.completion.current": "#9aa8a8" if dark else "#555555",
            "scrollbar.background": "bg:#1a1a1a" if dark else "bg:#eeeeee",
            "scrollbar.button": "bg:#3a3a3a" if dark else "bg:#cccccc",
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
                    display=_slash_display(spec, index),
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
        elif cmd in ARG_CHOICES:
            choices = list(ARG_CHOICES[cmd])
        elif cmd == "model" or routed in {"models", "select", "provider"}:
            parts = rest.split()
            sub = parts[0].lower() if parts else ""
            if routed in {"select"} or sub == "select":
                for name in self._providers_factory():
                    choices.append((name, "provider"))
            elif routed in {"models"} or sub == "list":
                for name in self._providers_factory():
                    choices.append((name, "provider"))
            elif routed == "provider" or sub == "provider":
                for name in self._providers_factory():
                    choices.append((name, "provider"))
            else:
                for mid in self._models_factory():
                    choices.append((str(mid), "model"))
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


def _slash_display(spec: SlashSpec, index: CommandIndex) -> str:
    mark = ""
    if spec.source == "skill":
        skill = next((s for s in index.skills if s.name.lower() == spec.name), None)
        if skill is not None and skill.source == "user":
            mark = f" {glyph('home')}"
    return f"/{spec.name}{mark}"


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
    muted = "#888888" if not is_dark() else "#6e6e6e"
    flash = ""
    if state.flash:
        flash = f"  {glyph('sep')} {_escape_html(state.flash)}"
    return HTML(
        f"<style fg='{brand}'>kite</style>"
        f"<style fg='{muted}'> {glyph('sep')} {_escape_html(tail)}{flash}</style>"
    )


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def history_path() -> Path:
    ensure_home()
    return kite_home() / "history"


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
        "mouse_support": False,
        "reserve_space_for_menu": 5,
    }
    if key_bindings is not None:
        kwargs["key_bindings"] = key_bindings
    if CompleteStyle is not None:
        kwargs["complete_style"] = CompleteStyle.COLUMN
    return PromptSession(**kwargs)


def make_repl_key_bindings(
    *,
    on_toggle_expand: Callable[[], str] | None = None,
    on_plan: Callable[[], str] | None = None,
    on_build: Callable[[], str] | None = None,
    on_status: Callable[[], str] | None = None,
) -> Any:
    """Keyboard shortcuts while the composer is focused."""
    if not _PT:
        return None
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()

    @bindings.add("c-o")
    def _expand(event) -> None:  # noqa: ANN001
        if on_toggle_expand:
            on_toggle_expand()
        event.app.invalidate()

    @bindings.add("c-p")
    def _plan(event) -> None:  # noqa: ANN001
        if on_plan:
            on_plan()
        event.app.invalidate()

    @bindings.add("c-b")
    def _build(event) -> None:  # noqa: ANN001
        if on_build:
            on_build()
        event.app.invalidate()

    @bindings.add("c-s")
    def _status(event) -> None:  # noqa: ANN001
        if on_status:
            on_status()
        event.app.invalidate()

    return bindings


def read_repl_line(
    *,
    session: Any,
    state: SessionUiState,
    fallback: Callable[[], str | None],
) -> str | None:
    """prompt_toolkit input with `/` dropdown; Rich Prompt if unavailable."""
    if session is None:
        return fallback()

    def _invalidate() -> None:
        try:
            app = getattr(session, "app", None)
            if app is not None:
                app.invalidate()
        except Exception:
            pass

    state._refresh = _invalidate
    placeholder_fg = "#888888" if not is_dark() else "#555555"
    brand = brand_ansi()
    try:
        return session.prompt(
            HTML(f"<style fg='{brand}'>{glyph('prompt')}</style> "),
            placeholder=HTML(f"<style fg='{placeholder_fg}'>/ commands · @file attach</style>"),
            bottom_toolbar=lambda: _toolbar_html(state),
        )
    except EOFError:
        return None
    except KeyboardInterrupt:
        return None
    finally:
        state._refresh = None
