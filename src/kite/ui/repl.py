"""Interactive REPL — prompt is live in <500ms; context loads lazily."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from kite.commands.loader import project_commands_dir, write_command_stub
from kite.config import UserConfig, kite_home
from kite.agent.harness import Harness, HarnessConfig
from kite.memory.store import MemoryStore
from kite.agent.mode import AgentMode, ApprovalMode, default_approval
from kite.plugins.loader import project_plugins_dir, write_plugin_stub
from kite.cli.slash import CommandIndex, help_text, resolve_slash
from kite.tools.store import TodoStore
from kite.ui.approval import ApprovalPolicy, make_approver
from kite.ui.commands import parse_slash
from kite.ui.git import GitCheckpoints, git_branch
from kite.ui.render import RunDisplay, render_status
from kite.ui.state import SessionUiState
from kite.ui.style import SYMBOL_PROMPT, make_console


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
        self.state.git_branch = git_branch(cwd)
        self._session_id: str | None = None
        self._harness: Harness | None = None

    def _approver(self):
        return make_approver(
            self.console,
            mode=self.state.mode,
            approval=self.state.approval,
            policy=self.policy,
            interactive=sys.stdin.isatty(),
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
            )
        )
        h.subscribe(self.display)
        return h

    def _read_input(self) -> str | None:
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
            self.console.print(
                Panel(help_text(self._index()), title="commands", border_style="cyan", padding=(0, 1))
            )
            return True
        if cmd == "plan" or (cmd == "mode" and arg == "plan"):
            self.state.mode = AgentMode.PLAN
            self.state.approval = ApprovalMode.READONLY
            self.console.print("[kite.plan]plan[/]  read-only · produce a checklist, then /build")
            return True
        if cmd == "build" or (cmd == "mode" and arg == "build"):
            self.state.mode = AgentMode.BUILD
            if self.state.approval is ApprovalMode.READONLY:
                self.state.approval = ApprovalMode.APPROVE
            self.console.print("[kite.build]build[/]  edits on · approval=" + self.state.approval.value)
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
            self.console.print(
                f"${self.state.cost:.4f}  ·  ctx {self.state.tokens}/{self.state.window or '—'} ({pct})  ·  calls {self.state.n_calls}"
            )
            return True
        if cmd == "expand":
            self.state.expanded_all = True
            self.console.print("[kite.muted]next tool outputs will be expanded[/]")
            return True
        if cmd == "trace":
            if self.state.last_trace:
                self.console.print(self.state.last_trace)
            elif self.state.last_error:
                self.console.print(self.state.last_error)
            else:
                self.console.print("[kite.muted]no traceback[/]")
            return True
        if cmd == "undo":
            ok, msg = self.git.undo()
            style = "kite.success" if ok else "kite.error"
            self.console.print(f"[{style}]{msg}[/]")
            return True
        if cmd == "new":
            cmd = "clear"
        if cmd == "clear":
            self._session_id = None
            self._harness = None
            self.todos = TodoStore()
            self.state.todos = []
            self.state.n_calls = 0
            self.state.cost = 0.0
            self.console.print("[kite.muted]session cleared[/]")
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
                self.console.print(f"[kite.success]model[/] {self.state.provider}/{self.state.model}")
                return True
            cfg = UserConfig.load()
            self.console.print(
                f"{cfg.default_provider}/{cfg.default_model or '—'}  ·  /model provider/id"
            )
            return True
        if cmd == "compact":
            self.console.print("[kite.pending]compact runs automatically before the next model call[/]")
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
            self._show_memory()
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
                f"${self.state.cost:.4f} · session {sid}"
            )
            return True
        if cmd == "session":
            self.console.print(self._session_id or "[kite.muted]no session yet[/]")
            return True
        if cmd == "home":
            home = kite_home()
            self.console.print(f"{home}")
            for name in ("commands", "skills", "plugins", "memory", "sessions"):
                self.console.print(f"  {home / name}")
            self.console.print(f"  {Path(self.cwd) / '.kite' / 'commands'}  (project)")
            return True
        return True

    def _show_skills(self, name: str) -> None:
        index = self._index()
        if name:
            skill = next((s for s in index.skills if s.name.lower() == name.lower()), None)
            if skill is None:
                self.console.print(f"[kite.error]unknown skill {name}[/]  — /skills")
                return
            self.console.print(Panel(skill.content, title=f"{skill.name}  {skill.path}", border_style="cyan"))
            return
        table = Table(title="skills  ·  /name to run")
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
            return
        index = self._index()
        table = Table(title="commands  ·  /commands new name")
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
        table = Table(title="plugins")
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
        notes = self.memory.notes()
        user_md = self.memory.user_markdown_path()
        proj_md = self.memory.project_markdown_path()
        self.console.print(
            f"[kite.muted]{self.memory.user_notes_path()}[/]\n[kite.muted]{self.memory.project_notes_path()}[/]"
        )
        if user_md.is_file() or proj_md.is_file():
            self.console.print(f"[kite.muted]pin files[/] {user_md}  {proj_md}")
        if not notes:
            self.console.print("[kite.muted]no notes  ·  /remember [user|project] text[/]")
            return
        for note in notes:
            self.console.print(f"  [kite.brand]{note.scope}/{note.id}[/]  {note.text}")

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
        banner.append("  type a task · /plan /build /help · /commit /explain  · Ctrl+C stops a turn", style="kite.muted")
        self.console.print(banner)

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
