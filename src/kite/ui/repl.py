"""Interactive REPL — prompt is live in <500ms; context loads lazily."""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.prompt import Prompt
from rich.text import Text

from kite.agent.mode import AgentMode, ApprovalMode, approval_display_name, default_approval, parse_approval_mode
from kite.cli.slash import CommandIndex, SlashResult, help_text, invalidate_command_index, resolve_slash
from kite.commands.loader import project_commands_dir, write_command_stub
from kite.config import UserConfig, kite_home
from kite.plugins.loader import project_plugins_dir, write_plugin_stub
from kite.tools.store import TodoStore
from kite.ui.complete import (
    BusyComposerHandlers,
    ComposerResult,
    SlashCompleter,
    apply_busy_composer_result,
    make_prompt_session,
    make_repl_key_bindings,
    read_repl_busy_composer,
    read_repl_line,
)
from kite.ui.empty import render_empty
from kite.ui.git import GitCheckpoints
from kite.ui.inbox import MessageInbox
from kite.ui.render import RunDisplay, render_compact_boundary
from kite.ui.state import SessionUiState
from kite.ui.status import render_status
from kite.ui.style import SYMBOL_FAIL, SYMBOL_PROMPT, make_console
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
        step_limit: int | None = None,
        cost_limit: float | None = None,
        wall_time_limit_seconds: int = 0,
        no_context: bool = False,
        no_compact: bool = False,
        no_guardrails: bool = False,
        role: str = "auto",
        long_task: bool = False,
        attachments: list | None = None,
    ):
        self.cwd = cwd
        self.provider = provider
        self.model = model
        self.config_name = config_name
        self.verbose = verbose
        self.step_limit = step_limit
        self.cost_limit = cost_limit
        self.wall_time_limit_seconds = wall_time_limit_seconds or 0
        self.no_context = no_context
        self.no_compact = no_compact
        self.no_guardrails = no_guardrails
        self.role = role or "auto"
        self.long_task = long_task
        self.console = make_console(stderr=True)
        self.state = SessionUiState(
            mode=mode,
            approval=approval or default_approval(mode),
        )
        self.display = RunDisplay(self.console, verbose=verbose, state=self.state)
        self.policy = None
        self.git = GitCheckpoints.open(cwd)
        self.todos = TodoStore()
        self._goal = None
        self._memory = None
        self._memory_in_prompt = False
        self.attachments: list = list(attachments or [])
        self._session_id: str | None = None
        self._harness = None
        self._harness_key: tuple | None = None
        self._model_resolved = False
        self._prompt = None
        self._reasoning_support = None
        self._model_cache: list[str] = []
        self._model_cache_provider: str | None = None
        self._pending_open = session_id
        self._flash: str = ""
        self._slash_handler_map: dict[str, Callable[[str], None]] | None = None
        self._inbox = MessageInbox()
        self._composer_action: dict[str, str] = {"kind": "submit"}
        self._busy = False
        self._quit_after_turn = False
        self._approval_coord = None
        self._approval_resolving = False
        self._approval_wake_sent = False
        self._composer_wake = False
        self._approval_panel_id: str | None = None
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()
        from kite.ui.fullscreen import FullscreenReducer
        from kite.ui.fullscreen.mode import UiDisplayMode

        self._fullscreen = FullscreenReducer()
        self._display_mode: UiDisplayMode = "compact"
        self._textual_app = None
        from kite.tools.jobs import JobRegistry

        self.jobs = JobRegistry(on_event=self._ui_event_handler)
        self._sync_from_config()

    def _sync_from_config(self) -> None:
        cfg = UserConfig.load()
        if not self.provider:
            self.provider = cfg.default_provider or self.provider
        if not self.model:
            self.model = cfg.default_model or self.model
        self.state.provider = self.provider or self.state.provider
        self.state.model = self.model or self.state.model

    @property
    def _approval_coordinator(self):
        coord = self._approval_coord
        if coord is None:
            from kite.application.policy import ApprovalCoordinator

            coord = ApprovalCoordinator(interactive=sys.stdin.isatty())
            coord.wake_main = self._wake_composer
            self._approval_coord = coord
        return coord

    @_approval_coordinator.setter
    def _approval_coordinator(self, value) -> None:
        self._approval_coord = value

    def _ensure_model_resolved(self) -> None:
        if self._model_resolved and self.provider and self.model:
            return
        from kite.providers.resolve import resolve_model

        cfg = UserConfig.load()
        resolved = resolve_model(provider=self.provider, model=self.model, config=cfg)
        self.provider = resolved.provider
        self.model = resolved.model
        self.state.provider = resolved.provider
        self.state.model = resolved.model
        self._model_resolved = True

    def _invalidate_harness(self) -> None:
        self._harness = None
        self._harness_key = None
        self._reasoning_support = None
        self._invalidate_completer_cache()

    def _effective_model_pair(self) -> tuple[str, str]:
        provider = self.provider or self.state.provider
        model = self.model or self.state.model
        if provider and model:
            return provider, model
        try:
            from kite.providers.resolve import resolve_model

            resolved = resolve_model(provider=provider, model=model)
            return resolved.provider, resolved.model
        except Exception:
            return provider or "", model or ""

    def _startup_banner(self) -> None:
        from kite.config.readiness import assess_setup_status_fast, format_setup_banner

        cfg = UserConfig.load()
        prov = self.provider or cfg.default_provider or "—"
        mod = self.model or cfg.default_model or "—"
        model_line = f"{prov}/{mod}"

        banner = Text()
        banner.append("kite", style="kite.brand")
        banner.append(" · ", style="kite.muted")
        banner.append(model_line, style="kite.highlight")
        banner.append(" · ", style="kite.muted")
        banner.append("/help", style="kite.brand")
        self.console.print(banner)

        status = assess_setup_status_fast(provider=self.provider, model=self.model)
        if not status.ready:
            self.console.print(
                "[kite.brand]Welcome![/]  Run [kite.brand]/setup[/] "
                "or [kite.brand]kite setup[/] to add an API key and pick a model."
            )
            note = format_setup_banner(status)
            if note:
                self.console.print(note)
        elif not cfg.default_model:
            self.console.print(
                "[kite.muted]Tip:[/]  [kite.brand]/model select[/] or [kite.brand]kite models -p groq --select[/]"
            )

    def _flash_note(self, text: str) -> None:
        self.state.set_flash(text)
        self.state.touch()

    @property
    def memory(self):
        if self._memory is None:
            from kite.memory.store import MemoryStore

            self._memory = MemoryStore.open(self.cwd)
        return self._memory

    def _approver(self):
        from kite.config import load_runtime_config
        from kite.ui.approval import ApprovalPolicy, make_approver

        if self.policy is None:
            self.policy = ApprovalPolicy.load()
        rcfg = load_runtime_config(self.config_name)
        return make_approver(
            self.console,
            mode=self.state.mode,
            approval=self.state.approval,
            policy=self.policy,
            interactive=sys.stdin.isatty(),
            trusted_paths=rcfg.guardrails.trusted_paths,
            workspace_cwd=self.cwd,
            coordinator=self._approval_coordinator,
        )

    def _ensure_policy(self) -> None:
        from kite.ui.approval import ApprovalPolicy

        if self.policy is None:
            self.policy = ApprovalPolicy.load()

    def _show_pending_approval_panel(self) -> None:
        req = self._approval_coordinator.pending
        if req is None:
            self._approval_panel_id = None
            return
        if self._approval_panel_id == req.request_id:
            return
        from kite.ui.approval import render_approval_panel

        self.console.print(
            render_approval_panel(
                req.tool,
                req.arguments,
                diff=req.diff,
                reason=req.reason,
                mandatory=req.mandatory,
            )
        )
        self._approval_panel_id = req.request_id

    def _resolve_approval_decision(self, decision: str) -> None:
        from kite.ui.approval import action_pattern

        req = self._approval_coordinator.pending
        if req is None:
            return
        self._ensure_policy()
        if decision in {"session", "always"} and not req.mandatory:
            pattern = action_pattern(req.tool, req.arguments)
            self.policy.remember(pattern, always=(decision == "always"))
        mapped = decision if decision in {"allow", "session", "always", "deny", "stop"} else "deny"
        self._approval_coordinator.resolve(mapped, request_id=req.request_id)
        self._approval_panel_id = None
        self.state.awaiting_approval = ""
        self.state.awaiting_approval_mandatory = False
        self.state.touch()

    def _handle_slash_while_busy(self, raw: str) -> None:
        parsed = resolve_slash(raw, self._index())
        if parsed.kind == "unknown":
            self._flash_note(parsed.message or "unknown command")
            return
        cmd, arg = parsed.command, parsed.arg
        cmd, arg = self._apply_legacy_slash(cmd, arg, parsed.legacy)
        cmd, arg = self._normalize_slash_cmd(cmd, arg)
        safe = {"tasks", "task", "status", "help", "jobs", "approve"}
        if cmd not in safe:
            self._flash_note("still working — /tasks · /status · /help · /jobs · /approve")
            return
        self._handle_slash(raw, parsed)

    def _prompt_app_running(self) -> bool:
        session = self._prompt
        if session is None:
            return False
        app = getattr(session, "app", None)
        return app is not None and bool(getattr(app, "is_running", False))

    def _ui_event_handler(self, event) -> None:
        if self._busy:
            self._ui_queue.put(event)
        else:
            self._apply_ui_event(event)

    def _apply_ui_event(self, event) -> None:
        self._fullscreen.apply_event(event)
        if self._display_mode == "fullscreen":
            self._maybe_refresh_fullscreen(event.kind)
        self.display(event)

    def _drain_ui_queue(self, *, limit: int = 500) -> None:
        for _ in range(limit):
            try:
                event = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            self._apply_ui_event(event)
        self._sync_queue_count()
        self.state.flush_pending_touch()

    def _busy_tick(self) -> None:
        self._drain_ui_queue()
        self._resolve_pending_approval()

    def _poll_pending_approval(self) -> None:
        """Toolbar poll — surface pending approval and break out of composer if needed."""
        req = self._approval_coordinator.pending
        if req is None:
            self._approval_wake_sent = False
            if self.state.awaiting_approval:
                self.state.awaiting_approval = ""
                self.state.awaiting_approval_mandatory = False
                self.state.touch()
            return
        self.state.awaiting_approval = req.tool
        self.state.awaiting_approval_mandatory = bool(getattr(req, "mandatory", False))
        self.state.touch()
        if self._prompt_app_running() and not self._approval_wake_sent:
            self._wake_composer()
            self._approval_wake_sent = True

    def _resolve_pending_approval(self) -> None:
        """Main-thread approval — composer keys when prompt_toolkit is active."""
        self._poll_pending_approval()
        req = self._approval_coordinator.pending
        if req is None:
            return
        if self._prompt is not None and (self._busy or self._prompt_app_running()):
            self._show_pending_approval_panel()
            return
        if self._approval_resolving:
            return
        self._approval_resolving = True
        try:
            from kite.ui.approval import prompt_approval

            self._ensure_policy()
            decision = prompt_approval(
                self.console,
                req.tool,
                req.arguments,
                diff=req.diff,
                reason=req.reason,
                policy=self.policy,
                mandatory=req.mandatory,
            )
            self._approval_coordinator.resolve(decision, request_id=req.request_id)
        finally:
            self._approval_resolving = False
            self._approval_panel_id = None
            self.state.awaiting_approval = ""
            self.state.awaiting_approval_mandatory = False
            self.state.touch()

    def _harness_cache_key(self) -> tuple:
        return (
            self.provider,
            self.model,
            self.state.mode.value,
            self.state.approval.value,
            self.state.sandbox_restricted,
            self._session_id,
            self.config_name,
            self.state.reasoning or "auto",
            self._memory_in_prompt,
            (self._goal.objective if self._goal and self._goal.active else ""),
            (self._goal.status if self._goal else ""),
            self.step_limit,
            self.cost_limit,
            self.wall_time_limit_seconds,
            self.no_context,
            self.no_compact,
            self.no_guardrails,
            self.role,
            self.long_task,
        )

    def _goal_objective_for_harness(self) -> str:
        if self._goal and self._goal.active:
            return self._goal.objective
        return ""

    def _sync_goal_to_session(self) -> None:
        if not self._session_id:
            return
        from kite.memory.goal import save_session_goal

        save_session_goal(self._session_id, self._goal)

    def _execution_mode(self) -> str:
        return "restricted" if self.state.sandbox_restricted else "host"

    def _make_harness(self, *, resume: bool = False, follow_up: str | None = None):
        from kite.agent.harness import Harness
        from kite.agent.harness_build import build_harness_config

        key = self._harness_cache_key()
        if self._harness is not None and self._harness_key == key:
            h = self._harness
            h.config.resume = resume and bool(self._session_id)
            h.config.follow_up = follow_up
            h.config.session_id = self._session_id
            h.config.attachments = list(self.attachments)
            h.config.memory_in_prompt = self._memory_in_prompt
            h.job_registry = self.jobs
            h.message_queue = self._inbox
            return h

        h = Harness(
            build_harness_config(
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
                execution_mode=self._execution_mode(),
                memory_in_prompt=self._memory_in_prompt,
                goal_objective=self._goal_objective_for_harness(),
                step_limit=self.step_limit,
                cost_limit=self.cost_limit,
                wall_time_limit_seconds=self.wall_time_limit_seconds,
                no_context=self.no_context,
                no_compact=self.no_compact,
                no_guardrails=self.no_guardrails,
                role=self.role,
                long_task=self.long_task,
            )
        )
        h.job_registry = self.jobs
        h.message_queue = self._inbox
        h.subscribe(self._ui_event_handler)
        self._harness = h
        self._harness_key = key
        return h

    def _provider_names(self) -> list[str]:
        from kite.providers.catalog import load_catalog

        return [p.name for p in load_catalog().list()]

    def _model_ids(self, provider: str | None = None) -> list[str]:
        provider = (provider or self.provider or self.state.provider or "").strip()
        if not provider:
            return []
        if self._model_cache and getattr(self, "_model_cache_provider", None) == provider:
            return self._model_cache
        try:
            from kite.providers.list_models import list_models_for_provider

            result = list_models_for_provider(provider)
            if result.ok:
                self._model_cache = [m.id for m in result.models]
                self._model_cache_provider = provider
        except Exception:
            return []
        return self._model_cache

    def _reasoning_info(self):
        if self._reasoning_support is not None:
            return self._reasoning_support
        from kite.models.reasoning import detect_reasoning

        provider, model = self._effective_model_pair()
        if not provider or not model:
            return None
        try:
            self._reasoning_support = detect_reasoning(provider, model)
        except Exception:
            self._reasoning_support = None
        return self._reasoning_support

    def _set_reasoning(self, raw: str, *, command: str = "") -> None:
        from kite.models.reasoning import encode_reasoning, reasoning_badge, split_reasoning

        info = self._reasoning_info()
        if command in {"thinking", "fast"}:
            if info is None or not info.can_both:
                self.console.print("[kite.muted]this API does not advertise both thinking and fast[/]")
                return
            token = raw.strip().lower()
            if token == command:
                token = ""
            match = self._match_effort(info, command, token)
            if match is None:
                return
            self.state.reasoning = encode_reasoning(command, match)
            self.console.print(f"[kite.muted]effort[/]  {reasoning_badge(self.state.reasoning)}")
            return

        mode, effort = split_reasoning(raw)
        if mode not in {"auto", "off"} and info is not None:
            if not info.supported:
                self.console.print("[kite.muted]this model does not advertise thinking/fast[/]")
                return
            if mode == "thinking" and not info.can_thinking:
                self.console.print("[kite.muted]no extended thinking on this model[/]")
                return
            if mode == "fast" and not info.can_fast:
                self.console.print("[kite.muted]no fast/low-effort on this model[/]")
                return
            if info.can_both and mode in {"thinking", "fast"}:
                match = self._match_effort(info, mode, effort)
                if match is None:
                    return
                effort = match
        encoded = encode_reasoning(mode, effort) if mode in {"thinking", "fast"} else mode
        self.state.reasoning = encoded
        self.console.print(f"[kite.muted]effort[/]  {reasoning_badge(encoded) or mode}")

    def _match_effort(self, info, mode: str, token: str) -> str | None:
        effort = info.default_effort(mode) if not token else token
        levels = info.levels_for(mode)
        match = next((lv for lv in levels if lv.lower() == effort.lower()), None)
        if match is None:
            self.console.print(f"[kite.muted]/{mode} {'|'.join(levels) or '—'}[/]")
        return match

    def _apply_appearance(self) -> None:
        from kite.ui.complete import prompt_style
        from kite.ui.theme import rich_theme

        self.console.use_theme(rich_theme())
        if self._prompt is not None:
            self._prompt.style = prompt_style()

    def _set_theme(self, raw: str) -> None:
        from kite.ui.theme import THEME_NAMES, set_theme, theme_label

        if not raw.strip():
            from kite.ui.theme import THEME_HELP

            picked = self._pick(
                [(name, THEME_HELP.get(name, name)) for name in THEME_NAMES],
                title="Color palette",
                current=theme_label().split(" ", 1)[0],
                noun="theme",
            )
            if not picked:
                self.console.print(f"[kite.muted]theme[/]  {theme_label()}")
                return
            raw = picked
        name = set_theme(raw, persist=True)
        if name is None:
            self.console.print(f"[kite.muted]/theme {'|'.join(THEME_NAMES)}[/]")
            return
        self._apply_appearance()
        self.console.print(f"[kite.muted]theme[/]  {theme_label()}")
        self.console.print("[kite.brand]kite[/]  [kite.success]ok[/]  [kite.pending]wait[/]  [kite.error]err[/]  [kite.muted]muted[/]")

    def _pick(
        self,
        items: list[tuple[str, str]],
        *,
        title: str,
        current: str | None = None,
        noun: str = "item",
    ) -> str | None:
        from kite.ui.pick import numbered_pick

        return numbered_pick(self.console, items, current=current, title=title, noun=noun)

    def _pick_session(self, title: str, *, query: str = "", show_table: bool = True) -> str | None:
        from kite.memory.session import list_sessions
        from kite.memory.session_format import render_sessions_table, session_pick_items

        rows = list_sessions(limit=30, query=query)
        if not rows:
            self.console.print(render_empty("no sessions", hint="/resume id"))
            return None
        if show_table:
            render_sessions_table(
                self.console,
                rows,
                title=title,
                current=self._session_id,
            )
        items = session_pick_items(rows, current=self._session_id)
        return self._pick(items, title=title, current=self._session_id, noun="session")

    def _print_sessions_list(self, query: str = "") -> None:
        from kite.memory.session import list_sessions
        from kite.memory.session_format import render_sessions_table

        rows = list_sessions(limit=30, query=query.strip())
        title = "Sessions"
        if query.strip():
            title += f"  ·  {query.strip()}"
        render_sessions_table(self.console, rows, title=title, current=self._session_id)

    def _set_font(self, raw: str) -> None:
        from kite.ui.theme import FONT_NAMES, glyph_preview, set_font

        if not raw.strip():
            from kite.ui.theme import FONT_HELP, current_font

            picked = self._pick(
                [(name, FONT_HELP.get(name, name)) for name in FONT_NAMES],
                title="Glyph pack",
                current=current_font(),
                noun="font",
            )
            if not picked:
                self.console.print(f"[kite.muted]font[/]  {current_font()}")
                return
            raw = picked
        name = set_font(raw, persist=True)
        if name is None:
            self.console.print(f"[kite.muted]/font {'|'.join(FONT_NAMES)}[/]")
            return
        self._apply_appearance()
        self.console.print(f"[kite.muted]font[/]  {name}  {glyph_preview()}")

    def _compact_now(self, _arg: str = "") -> None:
        if not self._session_id:
            self.console.print("[kite.muted]no session yet[/]")
            return
        from kite.agent.summarize import make_summarizer
        from kite.memory.compaction_ops import run_compaction
        from kite.memory.session import load_session
        from kite.providers.resolve import resolve_model

        try:
            session = load_session(self._session_id)
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        cfg = UserConfig.load()
        self._ensure_model_resolved()
        resolved = resolve_model(provider=self.provider, model=self.model, config=cfg)
        before = len(session.messages)
        summarizer = make_summarizer(cfg) if cfg.compaction_use_llm else None
        self.console.print("[kite.muted]compacting…[/]")
        result = run_compaction(
            session.messages,
            keep_recent_tokens=cfg.compaction_keep_recent_tokens,
            reserve_tokens=cfg.compaction_reserve_tokens,
            summarizer=summarizer,
            force=True,
            window=resolved.context_window,
            session_id=session.id,
            cwd=self.cwd,
            todos=self.todos.read(),
            meta=session.meta.to_dict(),
        )
        self.state.set_context_usage(
            total_tokens=result.usage.total_tokens,
            window=result.usage.window,
        )
        if not result.compacted:
            self.console.print("[kite.muted]already compact[/]")
            return
        session.replace_messages(result.messages)
        if result.checkpoint is not None:
            session.record_context_checkpoint(result.checkpoint.id, label=result.checkpoint.label, reason="pre_compact")
            self.console.print(f"[kite.muted]◇ saved {result.checkpoint.id}[/]")
        pct = self.state.context_pct
        boundary = render_compact_boundary(before, result.after, context_pct=pct)
        self.console.print(boundary)

    def _checkpoint_cmd(self, raw: str) -> None:
        if not self._session_id:
            self.console.print("[kite.muted]no session yet[/]")
            return
        from kite.memory.context_checkpoint import list_checkpoints, load_checkpoint, save_checkpoint
        from kite.memory.session import load_session

        parts = raw.strip().split(maxsplit=1)
        sub = (parts[0] if parts else "list").lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        try:
            session = load_session(self._session_id)
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")
            return

        if sub in {"", "list"}:
            rows = list_checkpoints(session.id)
            if not rows:
                self.console.print("[kite.muted]no checkpoints[/]")
                return
            for cp in rows:
                ratio = cp.context_usage.get("ratio")
                pct = f"{float(ratio):.0%}" if ratio is not None else "—"
                self.console.print(
                    f"[kite.muted]{cp.id}[/]  {cp.label}  ctx {pct}  "
                    f"{len(cp.messages)} msgs  {cp.reason}"
                )
            return

        if sub == "save":
            label = arg or "manual"
            cp = save_checkpoint(
                session_id=session.id,
                messages=session.messages,
                cwd=self.cwd,
                label=label,
                reason="manual",
                todos=self.todos.read(),
                meta=session.meta.to_dict(),
            )
            session.record_context_checkpoint(cp.id, label=cp.label, reason="manual")
            self.console.print(f"[kite.muted]◇ saved {cp.id}[/]  {label}")
            return

        if sub == "restore":
            if not arg:
                self.console.print("[kite.error]/checkpoint restore <id>[/]")
                return
            try:
                cp = load_checkpoint(session.id, arg)
            except (OSError, ValueError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            session.replace_messages(cp.messages)
            self.console.print(
                f"[kite.muted]◇ restored {cp.id}[/]  {len(cp.messages)} messages  ({cp.label})"
            )
            return

        if sub == "show":
            if not arg:
                self.console.print("[kite.error]/checkpoint show <id>[/]")
                return
            try:
                cp = load_checkpoint(session.id, arg)
            except (OSError, ValueError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            usage = cp.context_usage
            self.console.print(
                f"[kite.muted]{cp.id}[/]  {cp.label}\n"
                f"  {len(cp.messages)} messages  ·  ctx {usage.get('total_tokens', '?')} tok  "
                f"({usage.get('ratio', '?')})\n"
                f"  cwd {cp.cwd}  ·  {cp.reason}"
            )
            return

        self.console.print("[kite.error]/checkpoint save|list|restore|show[/]")

    def _handoff_cmd(self, raw: str) -> None:
        if not self._session_id:
            self.console.print("[kite.muted]no session yet[/]")
            return
        from kite.memory.handoff import write_handoff
        from kite.memory.session import load_session

        try:
            session = load_session(self._session_id)
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")
            return

        out = raw.strip()
        out_dir = Path(out).parent if out and (Path(out).suffix or "/" in out) else self.cwd
        if out and Path(out).suffix:
            out_dir = Path(out).parent

        bundle = write_handoff(
            session=session,
            cwd=self.cwd,
            todos=self.todos.read(),
            out_dir=out_dir,
            provider=self.provider or "",
            model=self.model or "",
        )
        session.record_context_checkpoint(bundle.checkpoint_id, label="handoff", reason="manual")
        self.console.print(f"[kite.muted]handoff[/]  {bundle.markdown_path}")
        self.console.print(f"[kite.muted]json[/]     {bundle.json_path}")
        self.console.print(f"[kite.muted]resume[/]  kite resume {bundle.session_id}")

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

    def _attach_clipboard_shortcut(self) -> str:
        from kite.ui.attach import load_clipboard

        try:
            att = load_clipboard()
            self._queue_attachment(att)
        except (OSError, ValueError) as e:
            return str(e)
        return f"attached {att.name} ({att.kind})"

    def _attach_clipboard(self, _arg: str = "") -> None:
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

    def _show_attachments(self, _arg: str = "") -> None:
        if not self.attachments:
            self.console.print("[kite.muted]none pending  ·  /attach path  ·  /clip[/]")
            return
        for item in self.attachments:
            self.console.print(f"  {item.source}  {item.name}  {item.kind}")

    def _apply_legacy_slash(self, cmd: str, arg: str, legacy: str) -> tuple[str, str]:
        if legacy == "provider":
            return "model", f"provider {arg}".strip()
        if legacy == "models":
            return "model", f"list {arg}".strip()
        if legacy == "select":
            return "model", f"select {arg}".strip()
        if legacy == "semantic":
            return "memory", "semantic"
        if legacy == "episodic":
            return "memory", "episodic"
        if legacy == "cost":
            return "status", arg
        if legacy == "collapse":
            return "collapse", arg
        if legacy in {"thinking", "fast"}:
            return "reasoning", legacy if not arg else arg
        return cmd, arg

    def _model_cmd(self, arg: str) -> None:
        token = arg.strip()
        lower = token.lower()

        if lower == "list" or lower.startswith("list "):
            provider = token[4:].strip() if lower.startswith("list ") else (self.provider or self.state.provider or "").strip()
            provider = provider.split()[0] if provider else provider
            if not provider:
                self.console.print("[kite.error]/model list <provider>[/]")
                return
            from kite.providers.list_models import list_models_for_provider

            try:
                result = list_models_for_provider(provider, refresh=True)
            except KeyError as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            if not result.ok:
                self.console.print(f"[kite.error]{result.error or 'no models'}[/]")
                return
            self._model_cache = [m.id for m in result.models]
            self._model_cache_provider = provider
            shown = result.models[:80]
            for m in shown:
                win = f"  {m.context_window}" if m.context_window else ""
                self.console.print(f"  {m.id}{win}")
            extra = len(result.models) - len(shown)
            if extra > 0:
                self.console.print(f"[kite.muted]  … {extra} more[/]")
            self.console.print("[kite.muted]  /model select[/] to pick one")
            return

        if lower == "refresh" or lower.startswith("refresh "):
            provider = token[7:].strip() if lower.startswith("refresh ") else ""
            self._refresh_models(provider)
            return

        if lower == "select" or lower.startswith("select "):
            provider = token[6:].strip() if lower.startswith("select ") else (self.provider or self.state.provider or "").strip()
            self._connect_flow(provider or None)
            return

        if lower == "provider" or lower.startswith("provider "):
            name = token.split(None, 1)[1].strip() if lower.startswith("provider ") else ""
            if not name:
                self._connect_flow()
                return
            self.provider = name
            self.state.provider = name
            self._model_cache = []
            self._model_cache_provider = None
            self._model_resolved = False
            self._invalidate_harness()
            self.console.print(f"[kite.muted]provider[/]  {name}  ·  /select or /login to continue")
            return

        if token:
            save = False
            for suffix in (" --save", " --persist"):
                if token.endswith(suffix):
                    save = True
                    token = token[: -len(suffix)].strip()
                    break
            if "/" in token:
                self.provider, self.model = token.split("/", 1)
            else:
                self.model = token
            self.state.provider = self.provider or self.state.provider
            self.state.model = self.model or self.state.model
            self._model_cache = []
            self._model_cache_provider = None
            self._model_resolved = True
            self._invalidate_harness()
            if save:
                cfg = UserConfig.load()
                cfg.default_provider = self.provider or cfg.default_provider
                cfg.default_model = self.model or cfg.default_model
                if self.provider:
                    cfg.provider_defaults[self.provider] = self.model or cfg.default_model
                cfg.save()
                self.console.print(f"[kite.success]saved[/] {self.state.provider}/{self.state.model}")
            else:
                self.console.print(
                    f"[kite.success]model[/] {self.state.provider}/{self.state.model}  "
                    "[kite.muted](session — add --save to persist)[/]"
                )
            return

        provider, model = self._effective_model_pair()
        cfg = UserConfig.load()
        self.console.print(
            f"session {provider}/{model or '—'}  ·  config {cfg.default_provider}/{cfg.default_model or '—'}\n"
            f"[kite.muted]/login  ·  /select  ·  /provider  ·  /model list[/]"
        )

    def _ensure_prompt(self):
        if self._prompt is not None:
            return self._prompt
        completer = SlashCompleter(
            self._index,
            models_factory=self._model_ids,
            providers_factory=self._provider_names,
            reasoning_info=self._reasoning_info,
        )

        def _toggle_expand() -> str:
            self.state.expanded_all = not self.state.expanded_all
            mode = "expanded" if self.state.expanded_all else "collapsed"
            return f"tool output {mode}"

        def _toggle_thinking() -> str:
            return self._toggle_thinking_display()

        def _expand_thinking_if_collapsed() -> str | None:
            if self.state.thinking_expanded:
                return None
            note = self._toggle_thinking_display(arg="expand")
            self._flash_note(note)
            return note

        def _plan() -> str:
            self._apply_plan_mode()
            return "plan · checklist only — /build to apply"

        def _build() -> str:
            self._apply_build_mode()
            return "build mode"

        def _status() -> str:
            from kite.ui.status import format_status_tail

            return format_status_tail(self.state)

        bindings = make_repl_key_bindings(
            on_toggle_expand=lambda: self._flash_note(_toggle_expand()),
            on_toggle_thinking=lambda: self._flash_note(_toggle_thinking()),
            on_expand_thinking=_expand_thinking_if_collapsed,
            on_plan=lambda: self._flash_note(_plan()),
            on_build=lambda: self._flash_note(_build()),
            on_status=lambda: self._flash_note(_status()),
            on_attach_clipboard=lambda: self._flash_note(self._attach_clipboard_shortcut()),
            on_clear_screen=lambda: self.console.clear(),
            on_toggle_fullscreen=lambda: self._flash_note(self._toggle_fullscreen_mode()),
            is_busy=lambda: self._busy,
            is_awaiting_approval=lambda: bool(self.state.awaiting_approval),
            can_remember_approval=lambda: bool(
                self.state.awaiting_approval and not self.state.awaiting_approval_mandatory
            ),
            action_slot=self._composer_action,
        )
        self._prompt = make_prompt_session(completer, key_bindings=bindings)
        return self._prompt

    def _read_input_rich(self) -> str | None:
        self.console.print(render_status(self.state))
        try:
            line = Prompt.ask(
                f"[kite.brand]{SYMBOL_PROMPT}[/]",
                console=self.console,
            )
        except EOFError:
            return None
        except KeyboardInterrupt:
            if self._busy:
                return "/stop"
            self.console.print("[kite.muted]Ctrl+D or /quit to leave[/]")
            return ""
        return line

    def _show_keys(self, _arg: str = "") -> None:
        from kite.config import UserConfig
        from kite.providers.catalog import load_catalog
        from kite.providers.credentials import (
            api_key_fingerprint,
            configured_providers,
            env_file_path,
        )
        from kite.ui.credentials import render_credentials_table_rows

        cfg = UserConfig.load()
        rows = configured_providers()
        catalog = load_catalog()
        fingerprints: dict[str, str] = {}
        for name, ok, env in rows:
            if not ok or env in {"local", "oauth", "—"}:
                continue
            try:
                fp = api_key_fingerprint(catalog.get(name))
            except KeyError:
                continue
            if fp:
                fingerprints[name] = fp

        self.console.print(
            render_credentials_table_rows(
                rows,
                default_provider=cfg.default_provider,
                fingerprints=fingerprints,
            )
        )
        self.console.print(
            f"[kite.muted]BYOK[/]  {env_file_path()}  "
            f"[kite.muted]BYOS[/]  Codex / Claude Code / Grok CLI  "
            f"[kite.muted]·[/]  /login provider  ·  /logout provider"
        )

    def _apply_connected(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self.state.provider = provider
        self.state.model = model
        self._model_cache = []
        self._model_cache_provider = None
        self._model_resolved = True
        self._invalidate_harness()

    def _connect_flow(self, provider: str | None = None, *, force_login: bool = False) -> None:
        from kite.providers.select import connect_interactive

        code, picked, model = connect_interactive(
            self.console,
            provider=provider or None,
            oauth_first=True,
            persist=True,
            login_if_needed=True,
            force_login=force_login,
        )
        if code == 0 and picked and model:
            self._apply_connected(picked, model)

    def _login_provider(self, arg: str) -> None:
        self._connect_flow(arg.strip() or None, force_login=True)

    def _logout_provider(self, arg: str) -> None:
        from kite.providers.credentials import logout_provider

        provider = arg.strip()
        if not provider:
            from kite.providers.credentials import configured_providers

            linked = [
                (name, f"{name}  {env}")
                for name, ok, env in configured_providers()
                if ok and env != "local"
            ]
            if not linked:
                self.console.print("[kite.muted]no linked providers[/]  ·  /login")
                return
            provider = self._pick(linked, title="Log out a provider", noun="provider") or ""
            if not provider:
                return
        code, msg = logout_provider(provider)
        style = "kite.success" if code == 0 else "kite.error"
        self.console.print(f"[{style}]{msg}[/]")

    def _read_input(self) -> ComposerResult:
        session = self._ensure_prompt()
        return read_repl_line(
            session=session,
            state=self.state,
            fallback=self._read_input_rich,
            busy=self._busy,
            action_slot=self._composer_action,
        )

    def _index(self) -> CommandIndex:
        return CommandIndex.load(self.cwd)

    def _invalidate_completer_cache(self) -> None:
        if self._prompt is not None:
            completer = getattr(self._prompt, "completer", None)
            if completer is not None and hasattr(completer, "invalidate"):
                completer.invalidate()

    def _invalidate_slash_cache(self) -> None:
        invalidate_command_index()
        self._invalidate_completer_cache()

    def _prewarm_composer(self) -> None:
        """Load slash index + prompt session before the first `/` menu opens."""
        import threading

        try:
            self._index()
            self._ensure_prompt()
        except Exception:
            pass

        def _warm_reasoning() -> None:
            try:
                self._reasoning_info()
            except Exception:
                pass

        threading.Thread(target=_warm_reasoning, name="kite-reasoning-prewarm", daemon=True).start()

    def _normalize_slash_cmd(self, cmd: str, arg: str) -> tuple[str, str]:
        if cmd == "mode" and arg in {"plan", "build"}:
            return arg, ""
        if cmd == "new":
            return "clear", arg
        if cmd == "sessions" and not arg:
            return "session", "list"
        if cmd == "skill" and not arg:
            return "skills", ""
        return cmd, arg

    def _slash_handlers(self) -> dict[str, Callable[[str], None]]:
        if self._slash_handler_map is not None:
            return self._slash_handler_map
        login = self._login_provider
        logout = self._logout_provider
        clip = self._attach_clipboard
        handlers = {
            "help": self._slash_help,
            "plan": self._slash_plan,
            "build": self._slash_build,
            "approve": self._slash_approve,
            "restricted": self._slash_restricted,
            "sandbox": self._slash_restricted,
            "cost": self._slash_cost,
            "expand": self._slash_expand,
            "live": self._slash_live,
            "expand-thinking": self._slash_expand_thinking,
            "collapse": self._slash_collapse,
            "trace": self._slash_trace,
            "undo": self._slash_undo,
            "clear": self._slash_clear,
            "init": self._slash_init,
            "login": login,
            "signin": login,
            "logout": logout,
            "signout": logout,
            "keys": self._show_keys,
            "setup": self._slash_setup,
            "model": self._model_cmd,
            "select": self._slash_model_select,
            "models": self._slash_model_list,
            "provider": self._slash_model_provider,
            "refresh": self._slash_refresh_models,
            "thinking": self._slash_thinking,
            "fast": self._slash_fast,
            "reasoning": self._slash_reasoning,
            "effort": self._slash_reasoning,
            "compact": self._compact_now,
            "checkpoint": self._checkpoint_cmd,
            "handoff": self._handoff_cmd,
            "attach": self._attach_path,
            "clip": clip,
            "clipboard": clip,
            "paste": clip,
            "detach": self._detach,
            "attachments": self._show_attachments,
            "skills": self._show_skills,
            "skill": self._run_skill,
            "commands": self._handle_commands,
            "plugins": self._handle_plugins,
            "memory": self._slash_memory,
            "user": self._show_user,
            "profile": self._show_profile,
            "working": self._show_working,
            "semantic": self._show_semantic,
            "episodic": self._show_episodic,
            "remember": self._remember,
            "forget": self._slash_forget,
            "status": self._slash_status,
            "privacy": self._slash_privacy,
            "stop": self._slash_stop,
            "steer": self._slash_steer,
            "tasks": self._slash_tasks,
            "jobs": self._slash_jobs,
            "agents": self._slash_agents,
            "kill": self._slash_kill,
            "resume": self._slash_resume,
            "goal": self._slash_goal,
            "session": self._handle_session,
            "home": self._slash_home,
            "theme": self._set_theme,
            "font": self._set_font,
            "fullscreen": self._slash_fullscreen,
        }
        self._slash_handler_map = handlers
        return handlers

    def _apply_plan_mode(self) -> None:
        self.state.mode = AgentMode.PLAN
        self.state.approval = ApprovalMode.READONLY
        self._invalidate_harness()

    def _apply_build_mode(self) -> None:
        self.state.mode = AgentMode.BUILD
        if self.state.approval is ApprovalMode.READONLY:
            self.state.approval = ApprovalMode.AUTO
        self._invalidate_harness()

    def _slash_help(self, arg: str) -> None:
        show_all = (arg or "").strip().lower() in {"all", "full", "advanced"}
        self.console.print(help_text(self._index(), all=show_all), style="kite.muted")

    def _terminal_size(self) -> tuple[int, int]:
        return self.console.width or 120, self.console.height or 40

    def _sync_fullscreen_session(self) -> None:
        from pathlib import Path

        from kite.agent.mode import approval_display_name

        repo = Path(self.cwd).name
        done = sum(1 for item in self.state.todos if item.status == "completed")
        self._fullscreen.sync_session(
            mode=self.state.mode.value,
            provider=self.provider or self.state.provider,
            model=self.model or self.state.model,
            branch=self.state.git_branch,
            repo=repo,
            approval=approval_display_name(self.state.approval),
            attachments=[a.name for a in self.attachments],
            queued=self.state.queued,
            context_pct=(self.state.context_pct or 0.0) * 100 if self.state.context_pct else 0.0,
            cost=self.state.cost,
            turn=self.state.turn,
            plan_done=done,
            plan_total=len(self.state.todos),
            display_mode=self._display_mode,
        )

    def _render_fullscreen(self) -> None:
        from kite.ui.fullscreen import render_fullscreen

        self._sync_fullscreen_session()
        self._fullscreen.model.display_mode = self._display_mode
        cols, rows = self._terminal_size()
        body = render_fullscreen(self.console, self._fullscreen.model, cols=cols, rows=rows)
        self.console.clear()
        self.console.print(body)

    def _toggle_fullscreen_mode(self) -> str:
        from kite.ui.fullscreen import can_show_fullscreen

        cols, rows = self._terminal_size()
        if self._display_mode == "compact":
            if not can_show_fullscreen(cols, rows):
                return "fullscreen needs ≥100×30 — staying compact"
            self._display_mode = "fullscreen"
            self.state.fullscreen = True
            self._render_fullscreen()
            return "fullscreen on  (Ctrl+Space · /fullscreen off)"
        self._exit_fullscreen_mode()
        return "fullscreen off"

    def _exit_fullscreen_mode(self) -> None:
        self._display_mode = "compact"
        self.state.fullscreen = False
        self.display.flush_transcript_buffer()

    def _maybe_refresh_fullscreen(self, kind: str) -> None:
        if self._display_mode != "fullscreen":
            return
        refresh_kinds = {
            "tool_start",
            "tool_end",
            "stream_delta",
            "diff",
            "verification_status",
            "verification_record",
            "approval",
            "todo",
            "agent_end",
            "turn_end",
            "submit_blocked",
            "error",
        }
        if kind in refresh_kinds:
            self._render_fullscreen()

    def _slash_fullscreen(self, arg: str) -> None:
        from kite.ui.fullscreen import can_show_fullscreen, preferred_display_mode

        token = (arg or "").strip().lower()
        cols, rows = self._terminal_size()
        if token in {"on", "enable"}:
            self._display_mode = preferred_display_mode(preference="fullscreen", cols=cols, rows=rows)
            if self._display_mode == "compact":
                self.console.print("[kite.pending]terminal too small for fullscreen (need ≥100×30)[/]")
                return
            self.state.fullscreen = True
            self._render_fullscreen()
            self.console.print("[kite.muted]fullscreen on[/]")
            return
        if token in {"off", "disable"}:
            self._exit_fullscreen_mode()
            self.console.print("[kite.muted]fullscreen off[/]")
            return
        if token in {"refresh", "redraw"}:
            if self._display_mode != "fullscreen":
                self.console.print("[kite.muted]fullscreen is off — /fullscreen on[/]")
                return
            self._render_fullscreen()
            return
        note = self._toggle_fullscreen_mode()
        if note:
            self.console.print(f"[kite.muted]{note}[/]")

    def _slash_plan(self, _arg: str) -> None:
        self._apply_plan_mode()
        self.console.print(
            "[kite.plan]plan mode[/]  read-only checklist — no edits; /build when ready"
        )

    def _slash_build(self, _arg: str) -> None:
        self._apply_build_mode()
        n = len(self.state.todos)
        if n:
            self.console.print(
                f"[kite.build]build mode[/]  edits on — continuing {n} checklist item(s)"
            )
        else:
            self.console.print("[kite.build]build mode[/]  default — edits are on")

    def _slash_approve(self, arg: str) -> None:
        token = (arg or "").strip()
        if not token:
            from kite.ui.commands import ARG_CHOICES

            picked = self._pick(
                ARG_CHOICES["approve"],
                title="Approval mode",
                current=approval_display_name(self.state.approval),
                noun="mode",
            )
            if not picked:
                return
            token = picked
        mode = parse_approval_mode(token or None, default=self.state.approval)
        self.state.approval = mode
        self._invalidate_harness()
        self.console.print(f"[kite.pending]approval[/] {approval_display_name(mode)}")

    def _slash_restricted(self, arg: str) -> None:
        token = (arg or "").strip().lower()
        if token in ("", "toggle"):
            picked = self._pick(
                [("on", "clamp paths to session cwd"), ("off", "host mode (default)")],
                title="Sandbox",
                current="on" if self.state.sandbox_restricted else "off",
                noun="mode",
            )
            if not picked:
                return
            token = picked
        if token in ("on", "true", "1", "yes"):
            self.state.sandbox_restricted = True
        elif token in ("off", "false", "0", "no"):
            self.state.sandbox_restricted = False
        else:
            self.console.print("[kite.error]use /restricted on|off[/]  (default: off / host mode)")
            return
        self._invalidate_harness()
        if self.state.sandbox_restricted:
            self.console.print("[kite.pending]restricted sandbox[/]  paths clamped to session cwd")
        else:
            self.console.print("[kite.success]host mode[/]  use set_cwd to work elsewhere; protected paths still blocked")
        self.state.touch()

    def _slash_cost(self, _arg: str) -> None:
        pct = f"{self.state.context_pct:.0%}" if self.state.context_pct is not None else "—"
        cache = ""
        if self.state.cache_hit_tokens:
            cache = f"  ·  cache {self.state.cache_hit_ratio:.0%} ({self.state.cache_hit_tokens} tok)"
        self.console.print(
            f"${self.state.cost:.4f}  ·  ctx {self.state.tokens}/{self.state.window or '—'} ({pct}){cache}  ·  calls {self.state.n_calls}"
        )

    def _slash_expand(self, _arg: str) -> None:
        self.state.expanded_all = not self.state.expanded_all
        mode = "expanded" if self.state.expanded_all else "collapsed"
        self.console.print(f"[kite.muted]tool output {mode}[/]  (/expand to toggle)")

    def _slash_live(self, arg: str) -> None:
        token = (arg or "").strip().lower()
        if token in {"agents", "crew", "subagents"}:
            self.state.live_subagents = not self.state.live_subagents
            mode = "on" if self.state.live_subagents else "off"
            self.console.print(
                f"[kite.muted]live subagents {mode}[/]  — crew tools + shell stream with worker prefix"
            )
        else:
            self.state.live_terminal = not self.state.live_terminal
            mode = "on" if self.state.live_terminal else "off"
            self.console.print(
                f"[kite.muted]live terminal {mode}[/]  — bash output streams  (/live agents for crew)"
            )
        self.state.touch()

    def _slash_expand_thinking(self, arg: str) -> None:
        note = self._toggle_thinking_display(arg=arg)
        self.console.print(f"[kite.muted]{note}[/]")

    def _toggle_thinking_display(self, *, arg: str = "") -> str:
        from kite.ui.render import render_reasoning_block

        token = (arg or "").strip().lower()
        if token == "collapse":
            self.state.thinking_expanded = False
            return "thinking collapsed (summary only)"
        if token == "expand":
            self.state.thinking_expanded = True
        else:
            self.state.thinking_expanded = not self.state.thinking_expanded
        if self.state.thinking_expanded:
            if self.state.last_thinking.strip():
                self.console.print(render_reasoning_block(self.state.last_thinking), highlight=False)
            return "thinking expanded"
        return "thinking collapsed (summary only)"

    def _slash_collapse(self, _arg: str) -> None:
        self.state.expanded_all = False
        self.console.print("[kite.muted]tool output collapsed[/]")

    def _slash_trace(self, _arg: str) -> None:
        if self.state.last_trace:
            self.console.print(self.state.last_trace)
        elif self.state.last_error:
            self.console.print(self.state.last_error)
        else:
            self.console.print("[kite.muted]no traceback saved yet[/]")

    def _slash_undo(self, _arg: str) -> None:
        ok, msg = self.git.undo()
        style = "kite.success" if ok else "kite.error"
        self.console.print(f"[{style}]{msg}[/]")

    def _slash_clear(self, _arg: str) -> None:
        self._reset_chat()
        self.console.print("[kite.muted]fresh start — conversation cleared[/]")

    def _slash_init(self, _arg: str) -> None:
        path = Path(self.cwd) / "KITE.md"
        if path.exists():
            self.console.print(f"[kite.pending]already exists[/] {path}")
            return
        path.write_text(KITE_MD_STUB, encoding="utf-8")
        self.console.print(f"[kite.success]wrote[/] {path}")

    def _slash_setup(self, _arg: str) -> None:
        from kite.cli.setup import run_setup_wizard

        code = run_setup_wizard(self.console)
        if code == 0:
            self._invalidate_harness()
            self._sync_from_config()

    def _slash_model_select(self, arg: str) -> None:
        self._connect_flow(arg.strip() or None)

    def _slash_refresh_models(self, arg: str) -> None:
        self._refresh_models(arg.strip())

    def _slash_model_list(self, arg: str) -> None:
        """Pick a live model for a provider and save it to ~/.kite/config.toml."""
        bits = arg.split()
        if bits and bits[0].lower() in {"refresh", "r"}:
            self._refresh_models(" ".join(bits[1:]).strip())
            return
        if not bits:
            self._connect_flow()
            return

        from kite.providers.catalog import load_catalog

        catalog = load_catalog()

        def _as_provider(name: str) -> str | None:
            try:
                return catalog.get(name).name
            except KeyError:
                return None

        providers = [_as_provider(b) for b in bits]
        if all(providers):
            names = list(dict.fromkeys(p for p in providers if p))
            if len(names) == 1:
                self._connect_flow(names[0])
                return
            picked = self._pick([(name, name) for name in names], title="Provider", noun="provider")
            if picked:
                self._connect_flow(picked)
            return

        provider = _as_provider(bits[0])
        if not provider:
            self.console.print(f"[kite.error]unknown provider[/]  {bits[0]}")
            return
        model = " ".join(bits[1:]).strip()
        if not model:
            self._connect_flow(provider)
            return
        from kite.config import UserConfig

        self._apply_connected(provider, model)
        cfg = UserConfig.load()
        cfg.default_provider = provider
        cfg.default_model = model
        cfg.provider_defaults[provider] = model
        path = cfg.save()
        self.console.print(f"[kite.success]saved[/] {provider}/{model}  →  {path}")

    def _refresh_models(self, provider_arg: str = "") -> None:
        """Clear caches and re-open the live model picker from the provider API."""
        from kite.providers.list_models import clear_model_list_cache

        provider = (provider_arg or self.provider or self.state.provider or "").strip() or None
        clear_model_list_cache(provider)
        self._model_cache = []
        self._model_cache_provider = None
        label = provider or "all providers"
        self.console.print(f"[kite.muted]refreshed[/]  {label}  ·  fetching from API…")
        self._connect_flow(provider)

    def _slash_model_provider(self, arg: str) -> None:
        if arg.strip():
            self._model_cmd(f"provider {arg}".strip())
            return
        self._connect_flow()

    def _slash_thinking(self, arg: str) -> None:
        self._set_reasoning(arg, command="thinking")

    def _slash_fast(self, arg: str) -> None:
        self._set_reasoning(arg, command="fast")

    def _slash_reasoning(self, arg: str) -> None:
        if not arg:
            from kite.ui.commands import ARG_CHOICES

            picked = self._pick(
                ARG_CHOICES["reasoning"],
                title="Effort",
                current=self.state.reasoning.split(":", 1)[0],
                noun="effort",
            )
            if not picked:
                from kite.models.reasoning import reasoning_badge

                badge = reasoning_badge(self.state.reasoning) or self.state.reasoning
                self.console.print(f"[kite.muted]effort[/]  {badge}")
                return
            self._set_reasoning(picked)
            return
        self._set_reasoning(arg)

    def _slash_memory(self, arg: str) -> None:
        which = arg.strip().lower()
        if which in {"semantic", "md", "markdown"}:
            self._show_semantic()
        elif which in {"episodic", "episodes", "sqlite"}:
            self._show_episodic()
        else:
            self._show_memory()

    def _slash_forget(self, arg: str) -> None:
        if not arg:
            self.console.print("[kite.error]/forget id or substring[/]")
            return
        result = self.memory.forget(arg)
        if result.total == 0:
            self.console.print("[kite.muted]no matching notes or episodes[/]")
            return
        for note in result.notes:
            self.console.print(f"[kite.success]forgot note[/] {note.scope}/{note.id}  {note.text}")
        for ep in result.episodes:
            self.console.print(f"[kite.success]forgot episode[/] {ep.id}  {ep.summary}")

    def _slash_status(self, _arg: str) -> None:
        from kite.config import kite_home
        from kite.memory.session_policy import persistence_mode, persistence_summary
        from kite.ui.shortcuts import shortcuts_help_text
        from kite.ui.status import status_detail_lines
        from kite.ui.theme import current_font, theme_label

        sid = self._session_id or "—"
        for line in status_detail_lines(self.state):
            self.console.print(f"[kite.muted]{line}[/]")
        self.console.print(
            f"[kite.muted]theme {theme_label()} · font {current_font()} · "
            f"sessions {persistence_mode()} · session {sid}"
            + (f" · queued {len(self._inbox)}" if self._inbox else "")
            + "[/]"
        )
        self.console.print(f"[kite.muted]home {kite_home()}[/]")
        summary = persistence_summary()
        if summary:
            self.console.print("[kite.muted]privacy[/]")
            for key, value in summary.items():
                self.console.print(f"  [kite.brand]{key.replace('_', ' ')}[/]  {value}")
        self.console.print(shortcuts_help_text(), style="kite.muted")

    def _slash_privacy(self, arg: str) -> None:
        from kite.memory.session_policy import (
            persistence_summary,
            set_persistence_mode,
            valid_persistence_modes,
        )

        text = (arg or "").strip()
        if not text or text.lower() in {"show", "status"}:
            summary = persistence_summary()
            self.console.print("[kite.muted]privacy & security[/]")
            for key, value in summary.items():
                label = key.replace("_", " ")
                self.console.print(f"  [kite.brand]{label}[/]  {value}")
            self.console.print("  [kite.muted]change sessions:[/]  /privacy sessions redacted|full|disabled")
            return

        parts = text.split()
        if parts[0].lower() != "sessions":
            self.console.print("[kite.muted]/privacy[/]  or  /privacy sessions redacted|full|disabled")
            return

        if len(parts) == 1:
            choices = [
                ("redacted", "sanitize secrets before write (default)"),
                ("full", "raw JSONL on disk (opt-in)"),
                ("disabled", "no session file writes"),
            ]
            picked = self._pick(choices, title="Session persistence", noun="mode")
            if not picked:
                return
            mode = set_persistence_mode(picked)
            self.console.print(f"[kite.success]session persistence[/]  {mode}")
            return

        mode = parts[1].lower()
        if mode not in valid_persistence_modes():
            allowed = ", ".join(sorted(valid_persistence_modes()))
            self.console.print(f"[kite.error]unknown mode {mode}[/]  — choose: {allowed}")
            return
        saved = set_persistence_mode(mode)
        self.console.print(f"[kite.success]session persistence[/]  {saved}")

    def _slash_stop(self, _arg: str) -> None:
        if not self._busy:
            self.console.print("[kite.muted]nothing running[/]  — session stays open")
            return
        self._request_stop()

    def _slash_steer(self, arg: str) -> None:
        text = (arg or "").strip()
        if not text:
            self.console.print("[kite.muted]/steer follow-up text[/]  or type while working, then Ctrl+G")
            return
        self._queue_steer(text)
        if self._busy:
            self._request_stop()
        else:
            self._run_task(text)

    def _slash_tasks(self, _arg: str) -> None:
        from kite.ui.status import active_task_count, format_running_status

        if self._busy:
            running = format_running_status(self.state) or "working"
            self.console.print(f"[kite.pending]running[/]  {running}")
        else:
            self.console.print("[kite.muted]nothing running[/]  — session stays open")
        if not self._inbox:
            self.console.print("[kite.muted]queue empty[/]  · Enter adds a follow-up while Kite works")
            return
        steer, follow = self._inbox.counts()
        self.console.print(
            f"[kite.muted]queued {len(self._inbox)}[/]  "
            f"({active_task_count(self.state)} total)"
            + (f"  ·  steer {steer}" if steer else "")
            + (f"  ·  follow-up {follow}" if follow else "")
        )
        for i, (msg, is_steer) in enumerate(self._inbox.entries(), start=1):
            preview = msg.replace("\n", " ").strip()
            if len(preview) > 100:
                preview = preview[:97] + "…"
            label = "steer" if is_steer else "follow-up"
            self.console.print(f"  {i}. [{label}] {preview}")

    def _slash_agents(self, arg: str) -> None:
        from kite.agent.subagent_profiles import (
            format_profile_trust,
            get_profile,
            init_user_profile,
            list_profiles,
            reload_profiles,
            user_profiles_dir,
        )
        from kite.ui.theme import glyph

        text = (arg or "").strip()
        parts = text.split(None, 1)
        sub = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub in {"profiles", "personas", "list"}:
            reload_profiles()
            profiles = list_profiles()
            if not profiles:
                self.console.print("[kite.muted]no profiles[/]  · /agents init my-role")
                return
            table = kite_table("subagent profiles")
            table.add_column("id")
            table.add_column("label")
            table.add_column("role")
            table.add_column("trust")
            table.add_column("description")
            for p in profiles:
                mark = f"{p.id} {glyph('home')}" if not p.bundled else p.id
                desc = p.description or p.prompt.split("\n", 1)[0][:50]
                table.add_row(mark, p.label, p.role, format_profile_trust(p), desc)
            self.console.print(table)
            self.console.print(
                f"[kite.muted]custom[/]  {user_profiles_dir()}/*.md  "
                "· /agents init <id>  · /agents show <id>"
            )
            return

        if sub == "init":
            name = rest or ""
            if not name:
                self.console.print("[kite.error]/agents init <id>[/]  · e.g. /agents init auditor")
                return
            try:
                path = init_user_profile(name)
            except (ValueError, FileExistsError, OSError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self.console.print(
                f"[kite.success]wrote[/] {path}  · edit markdown, then subagent profile={path.stem}"
            )
            return

        if sub == "show":
            pid = rest or ""
            if not pid:
                self.console.print("[kite.error]/agents show <id>[/]")
                return
            self._agents_show_profile(pid)
            return

        if sub == "reload":
            reload_profiles()
            self.console.print("[kite.success]reloaded[/] subagent profiles")
            return

        if sub and sub not in {"crew", "board"}:
            prof = get_profile(sub)
            if prof is not None:
                self._agents_show_profile(sub)
                return

        rows = [job for job in self.jobs.list(active_only=False) if job.kind == "subagent"]
        active = [job for job in rows if job.status == "running"]
        if not rows and not self.state.active_subagents:
            self.console.print(
                "[kite.muted]no crew yet[/]  · subagent tool · /agents profiles · /agents init <id>"
            )
            return
        table = kite_table("crew")
        table.add_column("id", style="kite.muted")
        table.add_column("profile", style="kite.muted")
        table.add_column("worker", style="kite.plan")
        table.add_column("outcome")
        table.add_column("prompt")
        for job in rows[-12:]:
            preview = (job.command or job.label or "").replace("\n", " ").strip()
            if len(preview) > 48:
                preview = preview[:45] + "…"
            payload = job.result_payload or {}
            outcome = str(payload.get("quality") or job.status or "running")
            elapsed = payload.get("elapsed_ms")
            if elapsed:
                outcome = f"{outcome} · {elapsed}ms"
            profile = job.profile or str(payload.get("profile") or "—")
            table.add_row(job.id[:8], profile, job.display_label(width=20), outcome, preview)
        self.console.print(table)
        if active:
            self.console.print(f"[kite.muted]{len(active)} running[/]  · /kill to stop one or all")
        else:
            self.console.print("[kite.muted]crew idle[/]  · /agents profiles to list personas")

    def _agents_show_profile(self, profile_id: str) -> None:
        from kite.agent.subagent_profiles import (
            format_profile_trust,
            get_profile,
            profile_source_path,
            reload_profiles,
        )

        reload_profiles()
        prof = get_profile(profile_id)
        if prof is None:
            self.console.print(f"[kite.error]unknown profile {profile_id}[/]  · /agents profiles")
            return
        src = profile_source_path(prof)
        trust = format_profile_trust(prof)
        self.console.print(
            f"[kite.plan]{prof.id}[/]  {prof.label}  role={prof.role}  trust={trust}"
        )
        if src:
            self.console.print(f"[kite.muted]{src}[/]")
        body = prof.prompt
        if not prof.bundled:
            body = prof.compose("").split("## Task", 1)[0].strip()
            if body.startswith("# Subagent:"):
                body = "\n".join(body.split("\n", 1)[1:]).strip()
        self.console.print(body or "[kite.muted](empty prompt)[/]")

    def _slash_jobs(self, _arg: str) -> None:
        rows = self.jobs.list(active_only=True)
        if not rows:
            self.console.print(render_empty("no background jobs", hint="bash background=true or live subagents"))
            return
        items = [
            (
                job.id,
                f"{job.kind:8}  {job.display_label(width=44)}"
                + (f"  pid {job.pid}" if job.pid else ""),
            )
            for job in rows
        ]
        picked = self._pick(items, title="Background jobs (pick to kill)", noun="job")
        if not picked:
            return
        if self.jobs.kill(picked):
            self.state.active_jobs = self.jobs.active_count()
            self.state.touch()
            self.console.print(f"[kite.success]killed[/] {picked}")
        else:
            self.console.print(f"[kite.muted]already gone[/] {picked}")

    def _slash_kill(self, arg: str) -> None:
        token = (arg or "").strip().lower()
        if not token:
            rows = self.jobs.list(active_only=True)
            choices = [("all", "kill every background job and live subagent")]
            choices.extend(
                (
                    job.id,
                    f"{job.kind}  {job.display_label(width=40)}"
                    + (f"  pid {job.pid}" if job.pid else ""),
                )
                for job in rows
            )
            if len(choices) == 1 and not rows:
                self.console.print("[kite.muted]no jobs to kill[/]  · /kill id|all")
                return
            picked = self._pick(choices, title="Kill job", noun="job")
            if not picked:
                return
            token = picked
        if token == "all":
            n = self.jobs.kill_all()
            self.state.active_jobs = self.jobs.active_count()
            self.state.touch()
            self.console.print(f"[kite.success]killed[/] {n} job{'s' if n != 1 else ''}")
            return
        if self.jobs.kill(token):
            self.state.active_jobs = self.jobs.active_count()
            self.state.touch()
            self.console.print(f"[kite.success]killed[/] {token}")
        else:
            self.console.print(f"[kite.error]no running job[/] {token}")

    def _teardown_jobs(self) -> None:
        n = self.jobs.kill_all()
        self.state.active_jobs = 0
        self.state.touch()
        if n:
            self.console.print(f"[kite.muted]stopped {n} background job{'s' if n != 1 else ''}[/]")

    def _slash_resume(self, arg: str) -> None:
        if not arg:
            sid = self._pick_session("Resume a session")
            if not sid:
                return
            self._open_session(sid)
            return
        self._open_session(arg)

    def _slash_goal(self, arg: str) -> None:
        from kite.memory.goal import SessionGoal

        text = (arg or "").strip()
        if not text:
            if self._goal and self._goal.objective:
                self.console.print(f"[kite.plan]goal[/]  {self._goal.status}")
                self.console.print(self._goal.objective[:2000])
                self.console.print("[kite.muted]/goal pause · resume · clear · edit …[/]")
            else:
                self.console.print(
                    "[kite.muted]no goal  ·  /goal Finish the migration and keep tests green[/]"
                )
            return
        low = text.lower()
        if low == "clear":
            self._goal = None
            self._sync_goal_to_session()
            self._invalidate_harness()
            self.console.print("[kite.success]goal cleared[/]")
            return
        if low == "pause":
            if self._goal and self._goal.objective:
                self._goal = SessionGoal(objective=self._goal.objective, status="paused")
                self._sync_goal_to_session()
                self._invalidate_harness()
                self.console.print("[kite.muted]goal paused[/]")
            else:
                self.console.print("[kite.muted]no active goal[/]")
            return
        if low == "resume":
            if self._goal and self._goal.objective:
                self._goal = SessionGoal(objective=self._goal.objective, status="active")
                self._sync_goal_to_session()
                self._invalidate_harness()
                self.console.print("[kite.success]goal resumed[/]")
            else:
                self.console.print("[kite.error]no goal  ·  /goal <objective>[/]")
            return
        if low.startswith("edit "):
            text = text[5:].strip()
        if not text:
            self.console.print("[kite.error]goal text required[/]")
            return
        preview = text if len(text) <= 72 else text[:69] + "…"
        self._goal = SessionGoal(objective=text[:4000], status="active")
        self._sync_goal_to_session()
        self._invalidate_harness()
        self.console.print(f"[kite.success]goal set[/]  {preview}")

    def _slash_home(self, _arg: str) -> None:
        from kite.memory.session_policy import persistence_mode

        home = kite_home()
        self.console.print(f"{home}")
        for name in ("commands", "skills", "subagents", "plugins", "memory", "goals", "sessions", "audit.jsonl"):
            self.console.print(f"  {home / name}")
        self.console.print(f"  sessions policy: {persistence_mode()}  ·  /privacy sessions")
        self.console.print(f"  {Path(self.cwd) / '.kite' / 'commands'}  (project)")

    def _handle_slash(self, raw: str, parsed: SlashResult | None = None) -> bool:
        """Return False to quit."""
        parsed = parsed or resolve_slash(raw, self._index())
        if parsed.kind == "prompt":
            tag = parsed.source or "command"
            self.console.print(f"[kite.muted]/{parsed.command}[/]  {tag}")
            self._run_task(parsed.prompt)
            return True
        if parsed.kind == "unknown":
            self.console.print(f"[kite.error]{parsed.message}[/]")
            return True

        cmd, arg = parsed.command, parsed.arg
        cmd, arg = self._apply_legacy_slash(cmd, arg, parsed.legacy)
        cmd, arg = self._normalize_slash_cmd(cmd, arg)

        if cmd == "quit":
            return False

        handler = self._slash_handlers().get(cmd)
        if handler is not None:
            handler(arg)
        else:
            self.console.print(f"[kite.error]unknown command /{cmd}[/]  — type /help")
        return True

    def _reset_chat(self) -> None:
        self._session_id = None
        self._invalidate_harness()
        self.todos = TodoStore()
        self.state.todos = []
        self.state.n_calls = 0
        self.state.cost = 0.0
        self.attachments = []
        self.state.pending_attach = 0

    def _print_session(self, session, *, tail: int = 12) -> None:
        from kite.memory.session_format import format_session_resume_hint

        meta = session.meta
        self.console.print(f"[kite.muted]{session.id}[/]  {format_session_resume_hint(meta)}")
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
            self.console.print(f"  [kite.brand]{role}[/] {content}")

    def _open_session(self, session_id: str) -> None:
        from kite.memory.session import load_session
        from kite.memory.session_format import format_session_resume_hint, suggest_sessions

        try:
            session = load_session(session_id)
        except FileNotFoundError:
            hints = suggest_sessions(session_id, limit=5)
            self.console.print(f"[kite.error]no session matching[/] {session_id!r}")
            for meta in hints:
                self.console.print(
                    f"  [kite.muted]/resume {meta.id}[/]  — {format_session_resume_hint(meta)}"
                )
            return
        except (OSError, ValueError) as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        self._invalidate_harness()
        self._session_id = session.id
        from kite.memory.goal import load_session_goal
        from kite.memory.session import load_session_todos

        self._goal = load_session_goal(session.id)
        restored = load_session_todos(session.id)
        if restored:
            self.todos.write(restored)
            self.state.set_todos(self.todos.read())
        if session.meta.provider:
            self.provider = session.meta.provider
            self.state.provider = session.meta.provider
        if session.meta.model:
            self.model = session.meta.model
            self.state.model = session.meta.model
        self._print_session(session, tail=8)
        self.console.print(
            f"[kite.success]opened[/] {session.id}  — type to continue  "
            f"[kite.muted]· kite resume {session.id}[/]"
        )

    def _handle_session(self, arg: str) -> None:
        from kite.memory.session import delete_all_sessions, delete_session, load_session

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
            self._print_sessions_list(rest)
            sid = self._pick_session("Open a session", query=rest, show_table=False)
            if not sid:
                return
            action = self._pick(
                [
                    ("open", "continue this chat"),
                    ("show", "print transcript"),
                    ("delete", "delete this session"),
                ],
                title=sid,
                current="open",
                noun="action",
            )
            if action == "open":
                self._open_session(sid)
            elif action == "show":
                try:
                    self._print_session(load_session(sid), tail=20)
                except (OSError, ValueError) as e:
                    self.console.print(f"[kite.error]{e}[/]")
            elif action == "delete":
                from kite.ui.pick import confirm

                if not confirm(self.console, f"Delete {sid}?", default=False):
                    self.console.print("[kite.muted]cancelled[/]")
                    return
                try:
                    gone = delete_session(sid)
                except (OSError, ValueError) as e:
                    self.console.print(f"[kite.error]{e}[/]")
                    return
                if gone.id == self._session_id:
                    self._reset_chat()
                extra = " + trajectory" if gone.trajectory else ""
                self.console.print(f"[kite.success]removed[/] {gone.id}{extra}")
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
                sid = self._pick_session("Open a session")
                if not sid:
                    return
                self._open_session(sid)
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
        self._open_session(raw)

    def _run_skill(self, arg: str) -> None:
        """Run a skill as the current turn (/skill name [args])."""
        raw = (arg or "").strip()
        if not raw:
            self._show_skills("")
            return
        name, _, extra = raw.partition(" ")
        if name.lower() in {"add", "install"}:
            self._show_skills(arg)
            return
        prompt = self._index().expand(f"skill:{name}", extra.strip())
        if prompt is None:
            prompt = self._index().expand(name, extra.strip())
        if prompt is None:
            self.console.print(f"[kite.error]unknown skill '{name}'[/]  — /skills")
            return
        self.console.print(f"[kite.muted]/skill {name}[/]")
        self._run_task(prompt)

    def _show_skills(self, name: str) -> None:
        raw = (name or "").strip()
        verb, _, rest = raw.partition(" ")
        if verb.lower() in {"add", "install"}:
            spec = rest.strip()
            if not spec:
                self.console.print("[kite.muted]/skills add @scope/pkg[/]  or  /skills add owner/repo")
                return
            try:
                from kite.skills.install import install_skill

                names = install_skill(spec, link_cwd=self.cwd)
            except (ValueError, RuntimeError, OSError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            listed = ", ".join(f"/{n}" for n in names)
            self.console.print(
                f"[kite.success]installed[/] {listed}  ·  ~/.kite/skills  "
                f"[kite.muted](untrusted — remote/npm/git skills require explicit install)[/]"
            )
            return
        from kite.skills.loader import format_skill_trust_badge
        from kite.ui.theme import glyph

        index = self._index()
        if raw:
            skill = next((s for s in index.skills if s.name.lower() == raw.lower()), None)
            if skill is None:
                self.console.print(f"[kite.error]unknown skill {raw}[/]  — /skills")
                return
            mark = f" {glyph('home')}" if skill.source == "user" else ""
            badge = format_skill_trust_badge(skill)
            self.console.print(f"[kite.muted]/{skill.name}{mark}[/]  {skill.path}  ·  {badge}")
            self.console.print(skill.content)
            return
        table = kite_table("skills")
        table.add_column("name")
        table.add_column("trust")
        table.add_column("description")
        for skill in index.skills:
            mark = f" {glyph('home')}" if skill.source == "user" else ""
            table.add_row(
                f"/{skill.name}{mark}",
                format_skill_trust_badge(skill),
                (skill.description or "")[:60],
            )
        self.console.print(table)
        if not index.skills:
            return
        picked = self._pick(
            [(s.name, f"{s.name}  {(s.description or '')[:50]}") for s in index.skills],
            title="Show a skill (empty = done)",
            noun="skill",
        )
        if picked:
            self._show_skills(picked)

    def _handle_commands(self, arg: str) -> None:
        if arg.startswith("new "):
            name = arg[4:].strip()
            try:
                path = write_command_stub(project_commands_dir(self.cwd), name)
            except (ValueError, FileExistsError, OSError) as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self.console.print(f"[kite.success]wrote[/] {path}  ·  edit then /{Path(path).stem}")
            self._invalidate_slash_cache()
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
            self._invalidate_slash_cache()
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

    def _show_memory(self, _arg: str = "") -> None:
        self._memory_in_prompt = True
        self._harness_key = None
        self._show_semantic()
        self.console.print()
        self._show_episodic()

    def _show_user(self, arg: str = "") -> None:
        from kite.memory.user_context import append_user_note, read_user, user_path

        text = arg.strip()
        if text.lower().startswith("add "):
            text = text[4:].strip()
        if text:
            try:
                note = append_user_note(text)
            except ValueError as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self.console.print(f"[kite.success]user[/]  {note}")
            self._harness_key = None
            return
        self.console.print(f"[kite.muted]{user_path()}[/]")
        body = read_user()
        if body:
            self.console.print(body)
        else:
            self.console.print("[kite.muted]empty  ·  /user add …  ·  edit USER.md directly[/]")

    def _show_profile(self, arg: str = "") -> None:
        from kite.memory.user_context import append_profile_note, profile_path, read_profile

        text = arg.strip()
        if text.lower().startswith("add "):
            text = text[4:].strip()
        if text:
            try:
                note = append_profile_note(text)
            except ValueError as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self.console.print(f"[kite.success]profile[/]  {note}")
            self._harness_key = None
            return
        self.console.print(f"[kite.muted]{profile_path()}[/]")
        body = read_profile()
        if body:
            self.console.print(body)
        else:
            self.console.print("[kite.muted]empty  ·  /profile add …  ·  edit PROFILE.md directly[/]")

    def _show_working(self, arg: str = "") -> None:
        from kite.memory.working_style import (
            append_signal,
            read_narrative,
            read_signals,
            render_working_context,
            working_path,
        )

        text = arg.strip()
        if text.lower().startswith("add "):
            text = text[4:].strip()
        if text:
            try:
                signal = append_signal(text)
            except ValueError as e:
                self.console.print(f"[kite.error]{e}[/]")
                return
            self.console.print(f"[kite.success]signal[/]  {signal}")
            self._harness_key = None
            return

        self.console.print(f"[kite.muted]{working_path()}[/]")
        rendered = render_working_context(self.memory)
        if rendered:
            self.console.print(rendered)
            return
        narrative = read_narrative()
        signals = read_signals()
        if narrative:
            self.console.print(narrative)
        for signal in signals:
            self.console.print(f"  - {signal}")
        if not narrative and not signals:
            self.console.print(
                "[kite.muted]no rhythm yet  ·  /working add …  ·  kite learns gently from sessions[/]"
            )

    def _show_semantic(self, _arg: str = "") -> None:
        notes = self.memory.notes()
        self.console.print(f"[kite.muted]{self.memory.user_markdown_path()}[/]")
        self.console.print(f"[kite.muted]{self.memory.project_markdown_path()}[/]")
        if not notes:
            self.console.print("[kite.muted]no notes  ·  /remember [user|project] text[/]")
            return
        for note in notes:
            self.console.print(f"  {note.scope}/{note.id}  {note.text}")

    def _show_episodic(self, _arg: str = "") -> None:
        rows = self.memory.episodes(limit=20)
        self.console.print(f"[kite.muted]{self.memory.episodic.user_path()}[/]")
        self.console.print(f"[kite.muted]{self.memory.episodic.project_path()}[/]")
        if not rows:
            self.console.print("[kite.muted]no episodes yet[/]")
            return
        for ep in rows:
            self.console.print(f"  {ep.id}  {ep.kind}  {ep.summary}")

    def _remember(self, arg: str) -> None:
        from kite.memory.store import MemoryScope

        scope: MemoryScope = "user"
        text = arg.strip()
        head, _, tail = text.partition(" ")
        if head.lower() == "project":
            scope = "project"
            text = tail.strip()
        elif head.lower() == "user":
            text = tail.strip()
        if not text:
            self.console.print("[kite.error]/remember [user|project] text[/]")
            return
        try:
            note = self.memory.remember(text, scope=scope)
        except ValueError as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        self.console.print(f"[kite.success]remembered[/] {note.scope}/{note.id}  {note.text}")
        self._memory_in_prompt = True
        self._harness_key = None

    def _sync_queue_count(self) -> None:
        steer, follow = self._inbox.counts()
        self.state.queued = len(self._inbox)
        self.state.queue_steer = steer
        self.state.queue_follow = follow
        entry = self._inbox.peek_entry()
        if entry is None:
            self.state.queue_head = ""
            self.state.queue_head_kind = ""
        else:
            head, is_steer = entry
            self.state.queue_head = head[:80] + ("…" if len(head) > 80 else "")
            self.state.queue_head_kind = "steer" if is_steer else "follow"
        self.state.touch()

    def _dequeue_to_composer(self) -> str:
        items = self._inbox.drain_all()
        if not items:
            self._flash_note("queue empty")
            return ""
        parts: list[str] = []
        for text, is_steer in items:
            prefix = "[steer] " if is_steer else ""
            parts.append(f"{prefix}{text}")
        self._sync_queue_count()
        self._flash_note("restored queued messages to composer")
        return "\n\n".join(parts)

    def _queue_message(self, text: str) -> None:
        if self._harness is not None:
            self._harness.inject_user_message(text)
        elif not self._inbox.enqueue(text):
            return
        self._sync_queue_count()
        preview = text[:80] + ("…" if len(text) > 80 else "")
        self._flash_note(f"queued {len(self._inbox)}  {preview}")

    def _queue_steer(self, text: str) -> None:
        if self._harness is not None:
            if not self._harness.inject_user_message(text, steer=True):
                return
        elif not self._inbox.steer(text):
            return
        self._sync_queue_count()
        preview = text[:80] + ("…" if len(text) > 80 else "")
        self._flash_note(f"steer  {preview}")

    def _request_stop(self) -> None:
        if self._harness is not None:
            self._harness.request_interrupt()
        self.state.interrupted = True
        self._flash_note("stopping…")

    def _wake_composer(self) -> None:
        """Interrupt prompt_toolkit so the main thread can show approval UI."""
        self._composer_wake = True
        candidates: list[Any] = []
        session = self._prompt
        if session is not None:
            app = getattr(session, "app", None)
            if app is not None:
                candidates.append(app)
        try:
            from prompt_toolkit.application import get_app

            candidates.append(get_app())
        except Exception:
            pass

        def _exit_app(app: Any) -> None:
            try:
                if getattr(app, "is_running", False):
                    app.exit(result="")
            except Exception:
                pass

        for app in candidates:
            if not getattr(app, "is_running", False):
                continue
            loop = getattr(app, "loop", None) or getattr(app, "_loop", None)
            if loop is not None:
                try:
                    loop.call_soon_threadsafe(lambda a=app: _exit_app(a))
                    return
                except Exception:
                    pass
            try:
                app.call_from_executor(lambda a=app: _exit_app(a))
                return
            except Exception:
                continue

    def _bind_session(self, harness) -> None:
        if harness.last_session:
            self._session_id = harness.last_session.id
            self._sync_goal_to_session()

    def _run_task_textual(self, task: str) -> None:
        """Run one turn under the Textual app (no prompt_toolkit composer)."""
        self._run_task(task, textual=True)

    def _run_task(self, task: str, *, textual: bool = False) -> None:
        from kite.ui.attach import collect_turn_attachments

        try:
            task, bundled = collect_turn_attachments(task, self.cwd, self.attachments)
        except ValueError as e:
            self.console.print(f"[kite.error]{e}[/]")
            return
        if not task.strip() and not bundled:
            self.console.print("[kite.muted]empty — type a task or /help[/]")
            return
        if not task.strip():
            task = "Look at the attached files."
        try:
            self._ensure_model_resolved()
        except Exception as e:
            self.console.print(f"[kite.error]{escape(str(e))}[/]  [kite.muted]/login · /select · kite setup[/]")
            return
        preview = task.replace("\n", " ").strip()
        self.state.set_running(label=preview[:80] or "working", kind="turn")
        self.attachments = list(bundled)
        self._sync_attach_count()

        from kite.config.runtime import load_runtime_config
        from kite.memory.continuity import build_continuity_brief, save_continuity
        from kite.memory.recovery import build_recovery_follow_up, decide_recovery_continue

        try:
            max_continues = max(0, int(load_runtime_config(self.config_name).max_budget_continues))
        except Exception:
            max_continues = 2
        max_continues = max(max_continues, 3 if self._goal and self._goal.active else max_continues)

        resume = bool(self._session_id)
        harness = self._make_harness(resume=resume, follow_up=task if resume else None)
        self._harness = harness
        harness.approver = self._approver()
        harness.checkpoints = self.git
        harness.todos = self.todos
        self._busy = True
        self.state.busy = True
        self.state.interrupted = False
        self.display._spin(False)

        continues_used = 0
        run_task = task
        box: dict = {}
        session = None if textual else self._ensure_prompt()

        def _slash_busy_hint() -> None:
            self._flash_note("Enter queues · Esc stop · Ctrl+G steer")

        def _composer_empty() -> None:
            if getattr(self, "_composer_wake", False):
                self._composer_wake = False
                return
            if self.state.awaiting_approval:
                return
            self._flash_note("Enter queues · Esc stop · Ctrl+G steer")

        def _spawn_and_wait(prompt_task: str) -> None:
            nonlocal box
            done = threading.Event()
            box = {}

            def worker() -> None:
                try:
                    from kite.application.cli import execute_harness_task, legacy_result_from_run

                    run_result = execute_harness_task(harness, prompt_task)
                    box["result"] = legacy_result_from_run(run_result)
                except KeyboardInterrupt:
                    box["interrupted"] = True
                except Exception as e:
                    box["err"] = e
                finally:
                    done.set()
                    self._wake_composer()

            threading.Thread(target=worker, daemon=True, name="kite-turn").start()
            if textual and self._textual_app is not None:
                self._textual_app.wait_for_turn(done)
            elif session is not None:
                read_repl_busy_composer(
                    session=session,
                    state=self.state,
                    action_slot=self._composer_action,
                    should_continue=lambda: not done.is_set(),
                    on_queue=self._queue_message,
                    on_stop=self._request_stop,
                    on_steer=self._queue_steer,
                    on_slash_while_busy=_slash_busy_hint,
                    on_busy_slash=self._handle_slash_while_busy,
                    on_approval=self._resolve_approval_decision,
                    on_eof=lambda: setattr(self, "_quit_after_turn", True),
                    on_empty=_composer_empty,
                    on_dequeue=self._dequeue_to_composer,
                    on_tick=self._busy_tick,
                    on_poll=self._busy_tick,
                )
            else:
                handlers = BusyComposerHandlers(
                    on_queue=self._queue_message,
                    on_stop=self._request_stop,
                    on_steer=self._queue_steer,
                    on_slash_while_busy=_slash_busy_hint,
                    on_busy_slash=self._handle_slash_while_busy,
                    on_eof=lambda: setattr(self, "_quit_after_turn", True),
                    on_empty=_composer_empty,
                )
                while not done.is_set():
                    self._busy_tick()
                    if self._approval_coordinator.pending:
                        time.sleep(0.05)
                        continue
                    got = self._read_input()
                    if done.is_set():
                        break
                    if got.kind == "steer":
                        self._queue_steer(got.text)
                        self._request_stop()
                        break
                    if apply_busy_composer_result(got, handlers):
                        break
            while not done.is_set():
                self._busy_tick()
                if done.wait(timeout=0.1):
                    break
            self._drain_ui_queue()

        while True:
            _spawn_and_wait(run_task)
            self._bind_session(harness)
            if box.get("err") is not None or box.get("interrupted"):
                break
            extra = box.get("result") or {}
            exit_status = str(extra.get("exit_status") or "")
            stats = extra.get("model_stats") if isinstance(extra.get("model_stats"), dict) else {}
            tool_calls = int(stats.get("api_calls") or extra.get("api_calls") or 0)
            goal_active = bool(self._goal and self._goal.active)
            action = decide_recovery_continue(
                exit_status=exit_status,
                continues_used=continues_used,
                max_continues=max_continues,
                goal_active=goal_active,
                goal_objective=self._goal_objective_for_harness(),
                todos=self.todos.read(),
                tool_call_count=tool_calls,
                inbox_queued=bool(self._inbox),
            )
            if action != "continue":
                break
            continues_used += 1
            messages: list[dict] = []
            agent = getattr(harness, "_runtime", None)
            if agent is not None and getattr(agent, "last_agent", None) is not None:
                messages = list(agent.last_agent.messages)
            elif self._session_id:
                try:
                    from kite.memory.session import load_session

                    messages = load_session(self._session_id).messages
                except (OSError, ValueError):
                    messages = []
            brief = build_continuity_brief(
                messages=messages,
                todos=self.todos.read(),
                task=preview,
            )
            try:
                from kite.memory.store import MemoryStore

                save_continuity(
                    store=MemoryStore.open(self.cwd),
                    brief=brief,
                    session_id=self._session_id or "",
                    cwd=self.cwd,
                )
            except Exception:
                pass
            run_task = build_recovery_follow_up(
                exit_status=exit_status,
                continuity_markdown=brief.to_markdown(),
                goal_objective=self._goal_objective_for_harness(),
            )
            label = "goal continue" if goal_active else "recovery continue"
            self.console.print(
                f"[kite.muted]{label} {continues_used}/{max_continues} — resuming…[/]"
            )
            self.state.set_running(
                label=f"{label} {continues_used}/{max_continues}",
                kind="turn",
            )
            self.state.busy = True
            self._busy = True
            self.display._spin(False)
            harness = self._make_harness(resume=True, follow_up=run_task)
            harness.approver = self._approver()
            harness.checkpoints = self.git
            harness.todos = self.todos

        self._busy = False
        self.state.busy = False
        self.state.clear_running()
        self.display.close()
        self._harness = None
        self._bind_session(harness)
        if box.get("err") is not None:
            err = box["err"]
            self.state.last_error = str(err)
            self.console.print(f"[kite.error]{SYMBOL_FAIL} {escape(str(err))}[/]  [kite.muted]/trace[/]")
            return
        self.attachments = []
        self._sync_attach_count()
        extra = box.get("result") or {}
        if extra.get("exit_status") == "Interrupted" or box.get("interrupted"):
            self.state.interrupted = True
            self.console.print("[kite.muted]session kept[/]  — type to continue, Ctrl+G after a stop to steer")
        if extra.get("exit_status") == "ProviderFault":
            self.state.last_error = str(extra.get("error") or "provider fault")
            sid = self._session_id or ""
            hint = f"kite resume {sid} --retry" if sid else "type to continue"
            self.console.print(
                f"[kite.pending]provider fault[/] — session saved. [kite.muted]{hint}[/]"
            )
            return
        if extra.get("exit_status") in {"LimitsExceeded", "TimeExceeded"}:
            self.state.last_error = str(extra.get("submission") or extra.get("content") or extra.get("exit_status"))
            return
        if extra.get("exit_status") in {"Error", "Stalled"}:
            self.state.last_error = str(extra.get("error") or extra.get("submission") or extra.get("exit_status"))
            self.state.last_trace = str(extra.get("traceback") or "")
            return
        if extra.get("cost") is not None:
            try:
                self.state.cost = float(extra["cost"])
            except (TypeError, ValueError):
                pass
        try:
            from kite.memory.working_style import observe_session_turn

            observe_session_turn(
                self.memory,
                session_id=self._session_id or "",
                mode=str(self.state.mode),
                approval=str(self.state.approval),
                extra=extra,
                interrupted=bool(self.state.interrupted),
            )
        except Exception:
            pass
        self.state.set_todos(self.todos.read())
        if self._session_id and self.todos.read():
            try:
                from kite.memory.session import persist_session_todos

                persist_session_todos(self._session_id, self.todos.read())
            except Exception:
                pass

    def run(self) -> int:
        from kite.ui.textual.app import should_use_textual_tui

        if should_use_textual_tui():
            from kite.ui.textual.run import run_textual_session

            return run_textual_session(self)

        from kite.ui.git import git_branch

        self.state.git_branch = git_branch(self.cwd)
        self._startup_banner()
        self._prewarm_composer()
        if self._pending_open:
            self._open_session(self._pending_open)
            self._pending_open = None

        while True:
            if self._quit_after_turn:
                self._teardown_jobs()
                self.console.print("[kite.muted]bye[/]")
                return 0
            if self._inbox:
                line = self._inbox.dequeue()
                assert line is not None
                self._sync_queue_count()
                preview = line[:80] + ("…" if len(line) > 80 else "")
                self.console.print(f"[kite.muted]› queued[/]  {preview}")
            else:
                got = self._read_input()
                if got.kind == "eof":
                    self._teardown_jobs()
                    self.console.print("\n[kite.muted]bye[/]")
                    return 0
                if got.kind == "stop":
                    self.console.print("[kite.muted]nothing running[/]  — session stays open")
                    continue
                if got.kind == "empty":
                    self.console.print("[kite.muted]empty — type a task or /help[/]")
                    continue
                line = got.text
                if not line or not str(line).strip():
                    self.console.print("[kite.muted]empty — type a task or /help[/]")
                    continue
            parsed = resolve_slash(line, self._index())
            if parsed.kind != "not_slash":
                if not self._handle_slash(line, parsed):
                    self._teardown_jobs()
                    self.console.print("[kite.muted]bye[/]")
                    return 0
                continue
            self._run_task(line)
        return 0
