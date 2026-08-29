"""Slash-command dropdown — name + one-line description, nested args."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from kite.cli.slash import CommandIndex, SlashSpec
from kite.config import ensure_home, kite_home
from kite.ui.attach import IMAGE_EXTS
from kite.ui.commands import ALIASES, ARG_CHOICES
from kite.ui.style import SYMBOL_PROMPT
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


PROMPT_STYLE = (
    Style.from_dict(
        {
            "prompt": "ansicyan",
            "placeholder": "#5a5a5a",
            "bottom-toolbar": "noreverse #6e6e6e bg:#121212",
            "completion-menu": "bg:#141414 #c8c8c8",
            "completion-menu.completion": "bg:#141414 #c8c8c8",
            "completion-menu.completion.current": "bg:#1a2e2e #e8ffff",
            "completion-menu.meta.completion": "#6e6e6e",
            "completion-menu.meta.completion.current": "#9aa8a8",
            "scrollbar.background": "bg:#1a1a1a",
            "scrollbar.button": "bg:#3a3a3a",
        }
    )
    if _PT
    else None
)


class SlashCompleter(Completer):  # type: ignore[misc]
    """When the line starts with `/`, offer builtins, commands, skills, plugins."""

    def __init__(
        self,
        index_factory: Callable[[], CommandIndex],
        *,
        models_factory: Callable[[], Iterable[str]] | None = None,
        providers_factory: Callable[[], Iterable[str]] | None = None,
        reasoning_ok: Callable[[], bool] | None = None,
    ) -> None:
        self._index_factory = index_factory
        self._models_factory = models_factory or (lambda: ())
        self._providers_factory = providers_factory or (lambda: ())
        self._reasoning_ok = reasoning_ok or (lambda: True)

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

        if not sep:
            prefix = cmd.lower()
            seen: set[str] = set()
            for spec in _visible_specs(index, reasoning_ok=self._reasoning_ok()):
                name = spec.name
                if name in seen:
                    continue
                if prefix and not (name.startswith(prefix) or prefix in name):
                    continue
                seen.add(name)
                meta = (spec.description or spec.source or "").strip()
                if spec.hint:
                    meta = f"{spec.hint}  {meta}".strip()
                yield Completion(
                    spec.name,
                    start_position=-len(cmd),
                    display=f"/{spec.name}",
                    display_meta=meta[:72],
                )
            return

        name = ALIASES.get(cmd.lower(), cmd.lower())
        yield from self._arg_completions(name, rest, index)

    def _arg_completions(self, cmd: str, rest: str, index: CommandIndex):
        token = rest
        # only complete the last token
        prefix = token.split()[-1] if token and not token.endswith(" ") else ""
        start = -len(prefix) if prefix else 0
        choices: list[tuple[str, str]] = []

        if cmd in ARG_CHOICES:
            choices = list(ARG_CHOICES[cmd])
        elif cmd in {"model", "models"}:
            for mid in self._models_factory():
                choices.append((str(mid), "model"))
        elif cmd in {"provider"}:
            for name in self._providers_factory():
                choices.append((str(name), "provider"))
        elif cmd in {"skills", "skill"}:
            for skill in index.skills:
                choices.append((skill.name, (skill.description or "")[:60]))
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

        needle = prefix.lower()
        for value, meta in choices:
            if needle and needle not in value.lower():
                continue
            yield Completion(value, start_position=start, display=value, display_meta=meta[:60])


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


def _visible_specs(index: CommandIndex, *, reasoning_ok: bool) -> list[SlashSpec]:
    rows: list[SlashSpec] = []
    seen: set[str] = set()
    for spec in index.specs.values():
        if spec.name in seen:
            continue
        if spec.name in {"thinking", "fast", "reasoning", "effort"} and not reasoning_ok:
            continue
        if ":" in spec.name and spec.source == "skill":
            continue
        seen.add(spec.name)
        rows.append(spec)
    rows.sort(key=lambda s: (0 if s.kind == "control" else 1, s.name))
    return rows


def _toolbar_html(state: SessionUiState) -> Any:
    rest: list[str] = [state.mode.value, state.approval.value]
    model = f"{state.provider}/{state.model}" if state.provider else (state.model or "—")
    rest.append(model)
    if state.reasoning and state.reasoning != "auto":
        rest.append(state.reasoning)
    if state.pending_attach:
        rest.append(f"+{state.pending_attach}")
    if state.context_pct is not None:
        rest.append(f"ctx {state.context_pct:.0%}")
    rest.append(f"${state.cost:.3f}")
    if state.git_branch:
        rest.append(state.git_branch)
    tail = " · ".join(rest)
    return HTML(
        f"<style fg='ansicyan'>kite</style>"
        f"<style fg='#6e6e6e'> · {_escape_html(tail)}</style>"
    )


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def history_path() -> Path:
    ensure_home()
    return kite_home() / "history"


def make_prompt_session(completer: SlashCompleter) -> Any:
    if not _PT:
        return None
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "history": FileHistory(str(path)),
        "completer": completer,
        "complete_while_typing": True,
        "auto_suggest": AutoSuggestFromHistory(),
        "style": PROMPT_STYLE,
        "mouse_support": False,
        "reserve_space_for_menu": 8,
    }
    if CompleteStyle is not None:
        kwargs["complete_style"] = CompleteStyle.COLUMN
    return PromptSession(**kwargs)


def read_repl_line(
    *,
    session: Any,
    state: SessionUiState,
    fallback: Callable[[], str | None],
) -> str | None:
    """prompt_toolkit input with `/` dropdown; Rich Prompt if unavailable."""
    if session is None:
        return fallback()
    try:
        return session.prompt(
            HTML(f"<style fg='ansicyan'>{SYMBOL_PROMPT}</style> "),
            placeholder=HTML("<style fg='#555555'>/ commands</style>"),
            bottom_toolbar=lambda: _toolbar_html(state),
        )
    except EOFError:
        return None
    except KeyboardInterrupt:
        return None
