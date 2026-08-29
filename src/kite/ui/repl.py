"""Interactive REPL — prompt is live in <500ms; context loads lazily."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.markup import escape
from rich.prompt import Prompt
from rich.text import Text

from kite.commands.loader import project_commands_dir, write_command_stub
from kite.config import UserConfig, kite_home
from kite.agent.harness import Harness, HarnessConfig
from kite.memory.store import MemoryStore
from kite.agent.mode import AgentMode, ApprovalMode, default_approval
from kite.plugins.loader import project_plugins_dir, write_plugin_stub
from kite.cli.slash import CommandIndex, help_text, invalidate_command_index, resolve_slash
from kite.tools.store import TodoStore
from kite.ui.approval import ApprovalPolicy, make_approver
from kite.ui.commands import parse_slash
from kite.ui.git import GitCheckpoints, git_branch
from kite.ui.complete import SlashCompleter, make_prompt_session, read_repl_line
from kite.ui.render import RunDisplay, render_status
from kite.ui.state import SessionUiState
from kite.ui.style import SYMBOL_COMPACT, SYMBOL_PROMPT, make_console
from kite.ui.tables import kite_table


KITE_MD_STUB = """# KITE.md

Project memory for Kite. Read on every session. Keep it short.

## What this repo is

## Conventions

## Do not

"""


class ChatSession:
    def __init__(
        self,
        *,
        cwd: str,
        provider: str | None = None,
        model: str | None = None,
        mode: AgentMode = AgentMode.BUILD,
        approval: ApprovalMode | None = None,
        config_name: str | None = None,
        verbose: bool = False,
        session_id: str | None = None,
    ):
        self.cwd = cwd
        self.provider = provider
        self.model = model
        self.config_name = config_name
        self.verbose = verbose
        self.console = make_console(stderr=True)
        self.state = SessionUiState(
            mode=mode,
            approval=approval or default_approval(mode),
        )
        self.display = RunDisplay(self.console, verbose=verbose, state=self.state)
        self.policy = ApprovalPolicy.load()
        self.git = GitCheckpoints.open(cwd)
        self.todos = TodoStore()
        self.memory = MemoryStore.open(cwd)
        self.attachments: list = []
        self.state.git_branch = git_branch(cwd)
        self._session_id: str | None = None
        self._harness: Harness | None = None
        self._prompt = None
        self._model_cache: list[str] = []
        self._pending_open = session_id

    def _approver(self):
        from kite.config import load_runtime_config

        rcfg = load_runtime_config(self.config_name)
        return make_approver(
            self.console,
            mode=self.state.mode,
            approval=self.state.approval,
            policy=self.policy,
            interactive=sys.stdin.isatty(),
            trusted_paths=rcfg.guardrails.trusted_paths,
            workspace_cwd=self.cwd,
        )

    def _make_harness(self, *, resume: bool = False, follow_up: str | None = None) -> Harness:
        h = Harness(
            HarnessConfig(
                provider=self.provider,
                model_name=self.model,
                cwd=self.cwd,
                session_id=self._session_id,
                resume=resume and bool(self._session_id),
                follow_up=follow_up,
                config_name=self.config_name,
                mode=self.state.mode.value,
                approval=self.state.approval.value,
                interactive=True,
                reasoning=self.state.reasoning or "auto",
                attachments=list(self.attachments),
            )
        )
        h.subscribe(self.display)
        return h

    def _provider_names(self) -> list[str]:
        from kite.providers.catalog import load_catalog

        return [p.name for p in load_catalog().list()]

    def _model_ids(self) -> list[str]:
        if self._model_cache:
            return self._model_cache
        provider = self.provider or self.state.provider
        if not provider:
            return []
        try:
            from kite.providers.list_models import list_models_for_provider

            result = list_models_for_provider(provider)
            if result.ok:
                self._model_cache = [m.id for m in result.models]
        except Exception:
            return []
        return self._model_cache

    def _reasoning_ok(self) -> bool:
        from kite.models.reasoning import detect_reasoning

        provider = self.provider or self.state.provider
        model = self.model or self.state.model
        if not provider or not model:
            return False
        return detect_reasoning(provider, model).supported

    def _set_reasoning(self, raw: str) -> None:
        from kite.models.reasoning import detect_reasoning, parse_mode

        mode = parse_mode(raw)
        provider = self.provider or self.state.provider
        model = self.model or self.state.model
        if mode != "auto" and provider and model:
            try:
                info = detect_reasoning(provider, model)
            except Exception:
                info = None
            if info is not None and mode != "off":
                if not info.supported:
                    self.console.print("[kite.muted]this model does not advertise thinking/fast[/]")
                    return
                if mode == "thinking" and not info.can_thinking:
                    self.console.print("[kite.muted]no extended thinking on this model[/]")
                    return
                if mode == "fast" and not info.can_fast:
                    self.console.print("[kite.muted]no fast/low-effort on this model[/]")
                    return
        self.state.reasoning = mode
        self.console.print(f"[kite.muted]effort[/]  {mode}")

    def _compact_now(self) -> None:
        if not self._session_id:
            self.console.print("[kite.muted]no session yet[/]")
            return
        from kite.agent.summarize import make_summarizer
        from kite.context.window import compact_messages
        from kite.memory.session import load_session

        try:
            session = load_session(self._session_id)
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        cfg = UserConfig.load()
        before = len(session.messages)
        summarizer = make_summarizer(cfg) if cfg.compaction_use_llm else None
        self.console.print("[kite.muted]compacting…[/]")
        compacted = compact_messages(
            session.messages,
            keep_recent_tokens=cfg.compaction_keep_recent_tokens,
            summarizer=summarizer,
            force=True,
        )
        if compacted == session.messages:
            self.console.print("[kite.muted]already compact[/]")
            return
        session.replace_messages(compacted)
        self.console.print(f"[kite.muted]{SYMBOL_COMPACT}  {before} → {len(compacted)}[/]")

    def _sync_attach_count(self) -> None:
        self.state.pending_attach = len(self.attachments)

    def _queue_attachment(self, item) -> None:
        from kite.ui.attach import MAX_ATTACHMENTS

        if len(self.attachments) >= MAX_ATTACHMENTS:
            self.console.print(f"[kite.error]too many attachments (max {MAX_ATTACHMENTS})[/]")
            return
        self.attachments.append(item)
        self._sync_attach_count()
        self.console.print(f"[kite.muted]attach  {item.source}  {item.name}  {item.kind}[/]")

    def _attach_path(self, raw: str) -> None:
        if not raw.strip():
            self.console.print("[kite.error]/attach path[/]")
            return
        from kite.ui.attach import load_file

        candidate = Path(raw.strip().strip('"')).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.cwd) / candidate
        try:
            self._queue_attachment(load_file(candidate, cwd=self.cwd))
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")

    def _attach_clipboard(self) -> None:
        from kite.ui.attach import load_clipboard

        self.console.print("[kite.muted]clipboard…[/]")
        try:
            self._queue_attachment(load_clipboard())
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")

    def _detach(self, raw: str) -> None:
        needle = raw.strip().lower()
        if not self.attachments:
            self.console.print("[kite.muted]no attachments[/]")
            return
        if not needle or needle == "all":
            n = len(self.attachments)
            self.attachments = []
            self._sync_attach_count()
            self.console.print(f"[kite.muted]dropped {n}[/]")
            return
        kept = [a for a in self.attachments if needle not in a.name.lower() and needle != a.name.lower()]
        if len(kept) == len(self.attachments):
            self.console.print("[kite.muted]no match[/]")
            return
        self.attachments = kept
        self._sync_attach_count()
        self.console.print("[kite.muted]dropped[/]")

    def _show_attachments(self) -> None:
        if not self.attachments:
            self.console.print("[kite.muted]none pending  ·  /attach path  ·  /clip[/]")
            return
        for item in self.attachments:
            self.console.print(f"  {item.source}  {item.name}  {item.kind}")

    def _ensure_prompt(self):
        if self._prompt is not None:
            return self._prompt
        completer = SlashCompleter(
            self._index,
            models_factory=self._model_ids,
            providers_factory=self._provider_names,
            reasoning_ok=self._reasoning_ok,
        )
        self._prompt = make_prompt_session(completer)
        return self._prompt

    def _read_input_rich(self) -> str | None:
        self.console.print(render_status(self.state))
        try:
            line = Prompt.ask(
                f"[kite.brand]{SYMBOL_PROMPT}[/]",
                console=self.console,
                default="",
                show_default=False,
            )
        except (EOFError, KeyboardInterrupt):
            self.console.print("\n[kite.muted]bye[/]")
            return None
        return line

    def _read_input(self) -> str | None:
        session = self._ensure_prompt()
        if session is None:
            return self._read_input_rich()
        line = read_repl_line(session=session, state=self.state, fallback=self._read_input_rich)
        if line is None:
            self.console.print("\n[kite.muted]bye[/]")
        return line

    def _index(self) -> CommandIndex:
        return CommandIndex.load(self.cwd)

    def _handle_slash(self, raw: str) -> bool:
        """Return False to quit."""
        parsed = resolve_slash(raw, self._index())
        if parsed.kind == "prompt":
            tag = parsed.source or "command"
            self.console.print(f"[kite.muted]/{parsed.command}[/]  {tag}")
            self._run_task(parsed.prompt)
            return True
        if parsed.kind == "unknown":
            self.console.print(f"[kite.error]{parsed.message}[/]")
            return True
        cmd, arg = parsed.command, parsed.arg

        if cmd == "quit":
            return False
        if cmd == "help":
            self.console.print(help_text(self._index()), style="kite.muted")
            return True
        if cmd == "plan" or (cmd == "mode" and arg == "plan"):
            self.state.mode = AgentMode.PLAN
            self.state.approval = ApprovalMode.READONLY
            self.console.print("[kite.plan]plan mode[/]  read-only — I'll suggest, not edit")
            return True
        if cmd == "build" or (cmd == "mode" and arg == "build"):
            self.state.mode = AgentMode.BUILD
            if self.state.approval is ApprovalMode.READONLY:
                self.state.approval = ApprovalMode.APPROVE
            self.console.print("[kite.build]build mode[/]  edits are on")
            return True
        if cmd == "approve":
            try:
                self.state.approval = ApprovalMode(arg or "approve")
            except ValueError:
                self.console.print("[kite.error]use /approve auto|approve|readonly[/]")
                return True
            self.console.print(f"[kite.pending]approval[/] {self.state.approval.value}")
            return True
        if cmd == "cost":
            pct = f"{self.state.context_pct:.0%}" if self.state.context_pct is not None else "—"
            cache = ""
            if self.state.cache_hit_tokens:
                cache = f"  ·  cache {self.state.cache_hit_ratio:.0%} ({self.state.cache_hit_tokens} tok)"
            self.console.print(
                f"${self.state.cost:.4f}  ·  ctx {self.state.tokens}/{self.state.window or '—'} ({pct}){cache}  ·  calls {self.state.n_calls}"
            )
            return True
        if cmd == "expand":
            self.state.expanded_all = not self.state.expanded_all
            mode = "expanded" if self.state.expanded_all else "collapsed"
            self.console.print(f"[kite.muted]tool output {mode}[/]  (/expand to toggle)")
            return True
        if cmd == "collapse":
            self.state.expanded_all = False
            self.console.print("[kite.muted]tool output collapsed[/]")
            return True
        if cmd == "trace":
            if self.state.last_trace:
                self.console.print(self.state.last_trace)
            elif self.state.last_error:
                self.console.print(self.state.last_error)
            else:
                self.console.print("[kite.muted]no traceback saved yet[/]")
            return True
        if cmd == "undo":
            ok, msg = self.git.undo()
            style = "kite.success" if ok else "kite.error"
            self.console.print(f"[{style}]{msg}[/]")
            return True
        if cmd == "new":
            cmd = "clear"
        if cmd == "clear":
            self._reset_chat()
            self.console.print("[kite.muted]fresh start — conversation cleared[/]")
            return True
        if cmd == "init":
            path = Path(self.cwd) / "KITE.md"
            if path.exists():
                self.console.print(f"[kite.pending]already exists[/] {path}")
                return True
            path.write_text(KITE_MD_STUB, encoding="utf-8")
            self.console.print(f"[kite.success]wrote[/] {path}")
            return True
        if cmd == "model":
            if arg:
                if "/" in arg:
                    self.provider, self.model = arg.split("/", 1)
                else:
                    self.model = arg
                self.state.provider = self.provider or self.state.provider
                self.state.model = self.model or self.state.model
                self._model_cache = []
                self.console.print(f"[kite.success]model[/] {self.state.provider}/{self.state.model}")
                return True
            cfg = UserConfig.load()
            self.console.print(
                f"{cfg.default_provider}/{cfg.default_model or '—'}  ·  /model provider/id"
            )
            return True
        if cmd == "provider":
            if arg:
                self.provider = arg
                self.state.provider = arg
                self._model_cache = []
                self.console.print(f"[kite.muted]provider[/]  {arg}")
                return True
            current = self.provider or self.state.provider or "—"
            names = "  ".join(self._provider_names()[:24])
            extra = f"\n[kite.muted]{names}[/]" if names else ""
            self.console.print(f"{current}  ·  /provider name{extra}")
            return True
        if cmd == "models":
            provider = (arg or self.provider or self.state.provider or "").strip()
            if not provider:
                self.console.print("[kite.error]/models needs a provider  ·  /provider name[/]")
                return True
            from kite.providers.list_models import list_models_for_provider

            try:
                result = list_models_for_provider(provider, refresh=True)
            except KeyError as e:
                self.console.print(f"[kite.error]{e}[/]")
                return True
            if not result.ok:
                self.console.print(f"[kite.error]{result.error or 'no models'}[/]")
                return True
            self._model_cache = [m.id for m in result.models]
            shown = result.models[:80]
            for m in shown:
                win = f"  {m.context_window}" if m.context_window else ""
                self.console.print(f"  {m.id}{win}")
            extra = len(result.models) - len(shown)
            if extra > 0:
                self.console.print(f"[kite.muted]  … {extra} more[/]")
            return True
        if cmd == "thinking":
            self._set_reasoning("thinking")
            return True
        if cmd == "fast":
            self._set_reasoning("fast")
            return True
        if cmd in {"reasoning", "effort"}:
            if not arg:
                self.console.print(f"[kite.muted]effort[/]  {self.state.reasoning}  ·  /reasoning auto|off|fast|thinking")
                return True
            self._set_reasoning(arg)
            return True
        if cmd == "compact":
            self._compact_now()
            return True
        if cmd == "attach":
            self._attach_path(arg)
            return True
        if cmd in {"clip", "clipboard", "paste"}:
            self._attach_clipboard()
            return True
        if cmd == "detach":
            self._detach(arg)
            return True
        if cmd == "attachments":
            self._show_attachments()
            return True
        if cmd == "skills" or (cmd == "skill" and not arg):
            self._show_skills(arg)
            return True
        if cmd == "commands":
            self._handle_commands(arg)
            return True
        if cmd == "plugins":
            self._handle_plugins(arg)
            return True
        if cmd == "memory":
            which = arg.strip().lower()
            if which in {"semantic", "md", "markdown"}:
                self._show_semantic()
            elif which in {"episodic", "episodes", "sqlite"}:
                self._show_episodic()
            else:
                self._show_memory()
            return True
        if cmd == "semantic":
            self._show_semantic()
            return True
        if cmd == "episodic":
            self._show_episodic()
            return True
        if cmd == "remember":
            self._remember(arg)
            return True
        if cmd == "forget":
            if not arg:
                self.console.print("[kite.error]/forget id or substring[/]")
                return True
            removed = self.memory.forget(arg)
            if not removed:
                self.console.print("[kite.muted]no matching notes[/]")
            else:
                for note in removed:
                    self.console.print(f"[kite.success]forgot[/] {note.scope}/{note.id}  {note.text}")
            return True
        if cmd == "status":
            sid = self._session_id or "—"
            self.console.print(
                f"{self.state.mode.value} · {self.state.approval.value} · "
                f"{self.state.provider or '—'}/{self.state.model or '—'} · "
                f"effort {self.state.reasoning} · "
                f"${self.state.cost:.4f} · session {sid}"
            )
            return True
        if cmd == "resume":
            if not arg:
                self.console.print("[kite.error]/resume <session-id>[/]  ·  /sessions")
                return True
            self._open_session(arg)
            return True
        if cmd in {"session", "sessions"}:
            if cmd == "sessions" and not arg:
                arg = "list"
            self._handle_session(arg)
            return True
        if cmd == "home":
            home = kite_home()
            self.console.print(f"{home}")
            for name in ("commands", "skills", "plugins", "memory", "sessions"):
                self.console.print(f"  {home / name}")
            self.console.print(f"  {Path(self.cwd) / '.kite' / 'commands'}  (project)")
            return True
        return True

    def _reset_chat(self) -> None:
        self._session_id = None
        self._harness = None
        self.todos = TodoStore()
        self.state.todos = []
        self.state.n_calls = 0
        self.state.cost = 0.0
        self.attachments = []
        self.state.pending_attach = 0

    def _print_session(self, session, *, tail: int = 12) -> None:
        meta = session.meta
        self.console.print(
            f"[kite.muted]{session.id}[/]  {meta.provider}/{meta.model}  "
            f"{meta.exit_status or 'open'}  {(meta.label or meta.task)[:60]}"
        )
        shown = session.messages[-tail:]
        if not shown:
            self.console.print("[kite.muted](empty transcript)[/]")
            return
        skipped = len(session.messages) - len(shown)
        if skipped > 0:
            self.console.print(f"[kite.muted]  … {skipped} earlier messages[/]")
        for m in shown:
            role = str(m.get("role") or "?")
            content = (m.get("content") or "").replace("\n", " ").strip()
            if len(content) > 160:
                content = content[:160] + "…"
            if not content:
                extra = m.get("extra") if isinstance(m.get("extra"), dict) else {}
                actions = extra.get("actions") if isinstance(extra, dict) else None
                if actions:
                    tools = ", ".join(str(a.get("tool") or "") for a in actions if isinstance(a, dict))
                    content = f"[tools: {tools}]" if tools else "[tool call]"
                else:
                    content = "—"
            self.console.print(f"  [cyan]{role}[/] {content}")

    def _open_session(self, session_id: str) -> None:
        from kite.memory.session import load_session

        try:
            session = load_session(session_id)
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        self._harness = None
        self._session_id = session.id
        if session.meta.provider:
            self.provider = session.meta.provider
            self.state.provider = session.meta.provider
        if session.meta.model:
            self.model = session.meta.model
            self.state.model = session.meta.model
        self._print_session(session, tail=8)
        self.console.print(f"[kite.success]opened[/] {session.id}  — type to pick up where you left off")

    def _handle_session(self, arg: str) -> None:
        from kite.memory.session import delete_all_sessions, delete_session, list_sessions, load_session

        raw = arg.strip()
        verb, _, rest = raw.partition(" ")
        verb = verb.lower()
        rest = rest.strip()
        if not raw:
            if self._session_id:
                self.console.print(self._session_id)
            else:
                self.console.print("[kite.muted]no session yet[/]  ·  /sessions")
            return
        if verb in {"list", "ls"}:
            rows = list_sessions(limit=20)
            if not rows:
                self.console.print("[kite.muted]no sessions[/]")
                return
            table = kite_table("sessions")
            table.add_column("id")
            table.add_column("model")
            table.add_column("label")
            for meta in rows:
                mark = " · current" if meta.id == self._session_id else ""
                table.add_row(meta.id, f"{meta.provider}/{meta.model}", (meta.label or "")[:50] + mark)
            self.console.print(table)
            self.console.print("[kite.muted]/session open <id>  ·  /session show <id>[/]")
            return
        if verb in {"show", "cat", "view"}:
            target = rest or self._session_id
            if not target:
                self.console.print("[kite.error]no session yet[/]  ·  /session show <id>")
                return
            try:
                session = load_session(target)
            except (OSError, ValueError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self._print_session(session, tail=20)
            return
        if verb in {"open", "resume", "use"}:
            if not rest:
                self.console.print("[kite.error]/session open <id>[/]  ·  /sessions")
                return
            self._open_session(rest)
            return
        if verb == "delete":
            target = rest
            if not target or target.lower() in {"this", "current", "."}:
                if not self._session_id:
                    self.console.print("[kite.error]no session yet[/]  ·  /session delete <id>")
                    return
                target = self._session_id
            if target.lower() == "all":
                gone = delete_all_sessions()
                self._reset_chat()
                self.console.print(f"[kite.success]removed[/] {len(gone)} session{'s' if len(gone) != 1 else ''}")
                return
            try:
                gone = delete_session(target)
            except (OSError, ValueError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            if gone.id == self._session_id:
                self._reset_chat()
            extra = " + trajectory" if gone.trajectory else ""
            self.console.print(f"[kite.success]removed[/] {gone.id}{extra}")
            return
        # Bare id: /session 20260829-…
        self._open_session(raw)

    def _show_skills(self, name: str) -> None:
        index = self._index()
        if name:
            skill = next((s for s in index.skills if s.name.lower() == name.lower()), None)
            if skill is None:
                self.console.print(f"[kite.error]unknown skill {name}[/]  — /skills")
                return
            self.console.print(f"[kite.muted]/{skill.name}[/]  {skill.path}")
            self.console.print(skill.content)
            return
        table = kite_table("skills")
        table.add_column("name")
        table.add_column("description")
        for skill in index.skills:
            table.add_row(f"/{skill.name}", (skill.description or "")[:70])
        self.console.print(table)

    def _handle_commands(self, arg: str) -> None:
        if arg.startswith("new "):
            name = arg[4:].strip()
            try:
                path = write_command_stub(project_commands_dir(self.cwd), name)
            except (ValueError, FileExistsError, OSError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self.console.print(f"[kite.success]wrote[/] {path}  ·  edit then /{Path(path).stem}")
            invalidate_command_index()
            return
        index = self._index()
        table = kite_table("commands")
        table.add_column("name")
        table.add_column("source")
        table.add_column("description")
        seen: set[str] = set()
        for spec in sorted(index.prompt_specs(), key=lambda s: s.name):
            if spec.source == "skill" or spec.name in seen:
                continue
            seen.add(spec.name)
            src = spec.plugin or spec.source
            table.add_row(f"/{spec.name}", src, (spec.description or "")[:60])
        if not seen:
            self.console.print("[kite.muted]no markdown commands  ·  /commands new review[/]")
            return
        self.console.print(table)

    def _handle_plugins(self, arg: str) -> None:
        if arg.startswith("init "):
            name = arg[5:].strip()
            try:
                path = write_plugin_stub(project_plugins_dir(self.cwd), name)
            except (ValueError, FileExistsError, OSError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self.console.print(
                f"[kite.success]wrote[/] {path}  ·  add commands/*.md and skills/*/SKILL.md"
            )
            invalidate_command_index()
            return
        plugins = self._index().plugins
        if arg:
            match = next((p for p in plugins if p.name.lower() == arg.lower()), None)
            if match is None:
                self.console.print(f"[kite.error]unknown plugin {arg}[/]")
                return
            cmds = ", ".join(f"/{c.name}" for c in match.commands) or "(no commands)"
            self.console.print(f"{match.name}  {match.path}\n{match.description or ''}\n{cmds}")
            return
        if not plugins:
            self.console.print("[kite.muted]no plugins  ·  /plugins init my-plugin[/]")
            return
        table = kite_table("plugins")
        table.add_column("name")
        table.add_column("source")
        table.add_column("commands")
        table.add_column("path")
        for plugin in plugins:
            table.add_row(
                plugin.name,
                plugin.source,
                str(len(plugin.commands)),
                str(plugin.path),
            )
        self.console.print(table)

    def _show_memory(self) -> None:
        self._show_semantic()
        self.console.print()
        self._show_episodic()

    def _show_semantic(self) -> None:
        notes = self.memory.notes()
        self.console.print(f"[kite.muted]{self.memory.user_markdown_path()}[/]")
        self.console.print(f"[kite.muted]{self.memory.project_markdown_path()}[/]")
        if not notes:
            self.console.print("[kite.muted]no notes  ·  /remember [user|project] text[/]")
            return
        for note in notes:
            self.console.print(f"  {note.scope}/{note.id}  {note.text}")

    def _show_episodic(self) -> None:
        rows = self.memory.episodes(limit=20)
        self.console.print(f"[kite.muted]{self.memory.episodic.user_path()}[/]")
        self.console.print(f"[kite.muted]{self.memory.episodic.project_path()}[/]")
        if not rows:
            self.console.print("[kite.muted]no episodes yet[/]")
            return
        for ep in rows:
            self.console.print(f"  {ep.id}  {ep.kind}  {ep.summary}")

    def _remember(self, arg: str) -> None:
        scope = "user"
        text = arg.strip()
        head, _, tail = text.partition(" ")
        if head.lower() in {"user", "project"}:
            scope = head.lower()
            text = tail.strip()
        if not text:
            self.console.print("[kite.error]/remember [user|project] text[/]")
            return
        try:
            note = self.memory.remember(text, scope=scope)  # type: ignore[arg-type]
        except ValueError as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        self.console.print(f"[kite.success]remembered[/] {note.scope}/{note.id}  {note.text}")

    def _run_task(self, task: str) -> None:
        from kite.ui.attach import collect_turn_attachments

        try:
            task, bundled = collect_turn_attachments(task, self.cwd, self.attachments)
        except ValueError as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        if not task.strip() and not bundled:
            return
        if not task.strip():
            task = "Look at the attached files."
        self.attachments = list(bundled)
        self._sync_attach_count()
        resume = bool(self._session_id)
        harness = self._make_harness(resume=resume, follow_up=task if resume else None)
        harness.approver = self._approver()
        harness.checkpoints = self.git
        harness.todos = self.todos
        try:
            result = harness.run(task)
        except KeyboardInterrupt:
            self.display.close()
            self.console.print("[kite.error]stopped[/]  [kite.muted]type a correction to steer[/]")
            if harness.last_session:
                self._session_id = harness.last_session.id
            return
        except Exception as e:
            self.display.close()
            self.state.last_error = str(e)
            self.console.print(f"[kite.error]✗ {escape(str(e))}[/]  [kite.muted]/trace[/]")
            return
        finally:
            self.display.close()
        self.attachments = []
        self._sync_attach_count()
        if harness.last_session:
            self._session_id = harness.last_session.id
        extra = result or {}
        if extra.get("cost") is not None:
            try:
                self.state.cost = float(extra["cost"])
            except (TypeError, ValueError):
                pass
        self.state.set_todos(self.todos.read())

    def run(self) -> int:
        # Cold start: chrome first, no model/context I/O.
        banner = Text()
        banner.append("kite", style="kite.brand")
        banner.append("  ", style="kite.muted")
        banner.append("›", style="kite.brand")
        banner.append("  /help", style="kite.muted")
        self.console.print(banner)
        if self._pending_open:
            self._open_session(self._pending_open)
            self._pending_open = None

        while True:
            line = self._read_input()
            if line is None:
                return 0
            line = line.strip()
            if not line:
                continue
            parsed = parse_slash(line)
            if parsed.kind != "not_slash":
                if not self._handle_slash(line):
                    return 0
                continue
            self._run_task(line)
        return 0
