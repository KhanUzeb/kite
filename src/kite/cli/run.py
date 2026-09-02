"""Kite CLI — run / resume / sessions / models / providers / config / context."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from kite.agent.mode import AgentMode, ApprovalMode, default_approval, parse_approval_mode


def _console():
    from kite.ui.style import make_console

    return make_console(stderr=True)


def _parse_mode(raw: str | None) -> AgentMode:
    try:
        return AgentMode((raw or "build").lower())
    except ValueError:
        return AgentMode.BUILD


def _parse_approval(raw: str | None, mode: AgentMode) -> ApprovalMode:
    fallback = ApprovalMode.AUTO if mode is AgentMode.BUILD else ApprovalMode.READONLY
    if raw:
        return parse_approval_mode(raw, default=default_approval(mode))
    return fallback


def _load_attachments(paths: list[str], task: str, cwd: str):
    from kite.ui.attach import collect_turn_attachments, load_file

    pending = []
    for raw in paths:
        pending.append(load_file(raw, cwd=cwd))
    leftover, bundled = collect_turn_attachments(task or "", cwd, pending)
    return leftover, bundled


def _wire_display(harness, console, args: argparse.Namespace):
    from kite.ui.render import make_run_display
    from kite.agent.mode import ApprovalMode
    from kite.ui.git import GitCheckpoints, git_branch
    from kite.ui.state import SessionUiState

    mode = _parse_mode(getattr(args, "mode", None))
    approval = _parse_approval(getattr(args, "approval", None), mode)
    state = SessionUiState(
        mode=mode,
        approval=approval,
        git_branch=git_branch(getattr(args, "cwd", os.getcwd())),
    )
    display = make_run_display(
        console,
        quiet=getattr(args, "quiet", False),
        verbose=getattr(args, "verbose", False),
        state=state,
    )
    harness.subscribe(display)
    if approval is not ApprovalMode.AUTO or mode is AgentMode.PLAN:
        from kite.config import load_runtime_config
        from kite.ui.approval import make_approver

        rcfg = load_runtime_config(getattr(args, "config", None))
        harness.approver = make_approver(
            console,
            mode=mode,
            approval=approval,
            interactive=sys.stdin.isatty() and not getattr(args, "quiet", False),
            trusted_paths=rcfg.guardrails.trusted_paths,
            workspace_cwd=getattr(args, "cwd", os.getcwd()),
        )
    if mode is AgentMode.BUILD:
        harness.checkpoints = GitCheckpoints.open(getattr(args, "cwd", os.getcwd()))
    return state


def cmd_run(args: argparse.Namespace) -> int:
    from kite.agent.harness import Harness, HarnessConfig
    from kite.config import ensure_home

    console = _console()
    task = args.task
    if args.stdin:
        task = sys.stdin.read().strip()
    mode = _parse_mode(args.mode)
    approval = _parse_approval(args.approval, mode)
    try:
        task, attachments = _load_attachments(
            getattr(args, "attach", None) or [],
            task or "",
            args.cwd,
        )
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return 2
    if not task.strip() and attachments:
        task = "Look at the attached files."
    if not task.strip():
        from kite.ui.pick import can_prompt

        if can_prompt() and not args.stdin:
            try:
                task = console.input("[kite.brand]Task[/]: ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Cancelled[/]")
                return 130
    if not task.strip():
        console.print("[red]Provide a task, --stdin, or --attach[/]")
        return 2
    harness = Harness(
        HarnessConfig(
            provider=args.provider,
            model_name=args.model,
            cwd=args.cwd,
            step_limit=args.steps,
            cost_limit=args.cost,
            wall_time_limit_seconds=args.time or 0,
            output_path=Path(args.output) if args.output else None,
            label=args.label or "",
            no_context=args.no_context,
            no_compact=args.no_compact,
            no_guardrails=args.no_guardrails,
            config_name=args.config,
            mode=mode.value,
            approval=approval.value,
            interactive=False,
            attachments=attachments,
            role=getattr(args, "role", "auto"),
            long_task=bool(getattr(args, "long", False)),
        )
    )
    _wire_display(harness, console, args)
    try:
        result = harness.run(task)
    except Exception as e:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            console.print(f"[red]{e}[/]")
        return 1
    finally:
        harness.teardown_jobs()

    sid = harness.last_session.id if harness.last_session else ""
    if getattr(args, "json", False):
        data = {
            "ok": result.get("exit_status") == "Submitted",
            "exit_status": result.get("exit_status"),
            "submission": result.get("submission"),
            "session_id": sid,
            "verification": result.get("verification"),
        }
        print(json.dumps(data, indent=2))
        return 0 if data["ok"] else 1

    console.print(
        f"[bold]exit[/]={result.get('exit_status')}  "
        f"[bold]session[/]={sid}  "
        f"trajectory={ensure_home() / 'trajectories' / f'{sid}.json'}"
    )
    if result.get("exit_status") == "ProviderFault":
        console.print(
            f"[kite.pending]provider fault[/] — session saved. "
            f"[kite.muted]retry: kite resume {sid} \"continue\"[/]"
        )
    elif result.get("exit_status") == "Error":
        console.print(f"[red]{result.get('error')}[/]")
        if result.get("traceback"):
            console.print("[dim]See session log or re-run with -v for full traceback[/]")
    return 0 if result.get("exit_status") == "Submitted" else 1


def cmd_chat(args: argparse.Namespace) -> int:
    from kite.ui.repl import ChatSession

    mode = _parse_mode(getattr(args, "mode", None))
    approval = _parse_approval(getattr(args, "approval", None), mode)
    if getattr(args, "approval", None) is None:
        approval = default_approval(mode)
    session = ChatSession(
        cwd=getattr(args, "cwd", None) or os.getcwd(),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        mode=mode,
        approval=approval,
        config_name=getattr(args, "config", None),
        verbose=getattr(args, "verbose", False),
        session_id=getattr(args, "session", None),
    )
    return session.run()


def _session_pick_items(rows) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for meta in rows:
        label = (
            f"{meta.id}  {meta.provider}/{meta.model}  "
            f"{meta.exit_status or '-'}  {(meta.label or meta.task or '')[:40]}"
        )
        items.append((meta.id, label))
    return items


def _pick_session_id(console, *, title: str = "Pick a session") -> str | None:
    from kite.memory.session import list_sessions
    from kite.ui.pick import numbered_pick

    rows = list_sessions(limit=20)
    if not rows:
        console.print("[dim]no sessions[/]")
        return None
    return numbered_pick(
        console,
        _session_pick_items(rows),
        current=None,
        title=title,
        noun="session",
    )


def cmd_resume(args: argparse.Namespace) -> int:
    from kite.agent.harness import Harness, HarnessConfig

    if not getattr(args, "session", None):
        from kite.ui.pick import can_prompt

        console = _console()
        if not can_prompt():
            console.print("[red]session id required[/]  —  kite resume <id>  or run in a terminal to pick")
            return 2
        picked = _pick_session_id(console, title="Resume a session")
        if not picked:
            return 130
        args.session = picked

    follow = args.message or args.task
    if not follow:
        return cmd_chat(args)
    console = _console()
    mode = _parse_mode(args.mode)
    approval = _parse_approval(args.approval, mode)
    try:
        follow, attachments = _load_attachments(
            getattr(args, "attach", None) or [],
            follow,
            args.cwd,
        )
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return 2
    harness = Harness(
        HarnessConfig(
            provider=args.provider,
            model_name=args.model,
            cwd=args.cwd,
            step_limit=args.steps,
            cost_limit=args.cost,
            session_id=args.session,
            resume=True,
            follow_up=follow,
            no_context=args.no_context,
            no_compact=args.no_compact,
            no_guardrails=args.no_guardrails,
            config_name=args.config,
            mode=mode.value,
            approval=approval.value,
            interactive=False,
            attachments=attachments,
            long_task=bool(getattr(args, "long", False)),
        )
    )
    _wire_display(harness, console, args)
    try:
        result = harness.run(follow)
    except Exception as e:
        console.print(f"[red]{e}[/]")
        return 1
    finally:
        harness.teardown_jobs()
    console.print(f"[bold]exit[/]={result.get('exit_status')}  session={args.session}")
    return 0 if result.get("exit_status") == "Submitted" else 1


def cmd_sessions(args: argparse.Namespace) -> int:
    from rich.panel import Panel
    from rich.table import Table

    from kite.config import kite_home
    from kite.memory.session import delete_all_sessions, delete_session, list_sessions, load_session
    from kite.ui.pick import can_prompt, confirm, numbered_pick

    console = _console()
    if args.delete_all:
        rows = list_sessions(limit=10_000)
        if not rows:
            console.print("[dim]no sessions[/]")
            return 0
        if not args.yes:
            if can_prompt():
                if not confirm(console, f"Delete {len(rows)} sessions?", default=False):
                    console.print("[yellow]Cancelled[/]")
                    return 130
            else:
                console.print(f"[red]delete {len(rows)} sessions? pass -y to confirm[/]")
                return 1
        deleted = delete_all_sessions()
        console.print(f"deleted {len(deleted)} session{'s' if len(deleted) != 1 else ''}")
        return 0
    if args.delete:
        failed = 0
        for sid in args.delete:
            try:
                gone = delete_session(sid)
            except (OSError, ValueError) as e:
                console.print(f"[red]{e}[/]")
                failed += 1
                continue
            extra = " + trajectory" if gone.trajectory else ""
            console.print(f"deleted {gone.id}{extra}")
        return 1 if failed else 0
    if args.show:
        session = load_session(args.show)
        console.print(Panel(json.dumps(session.meta.to_dict(), indent=2), title=session.id))
        for i, m in enumerate(session.messages[-args.tail :], 1):
            role = m.get("role")
            content = (m.get("content") or "")[:200].replace("\n", " ")
            console.print(f"[dim]{i}[/] [cyan]{role}[/] {content}")
        return 0

    rows = list_sessions(limit=args.limit)
    if can_prompt() and rows:
        sid = numbered_pick(
            console,
            _session_pick_items(rows),
            current=None,
            title=f"Sessions in {kite_home() / 'sessions'}",
            noun="session",
        )
        if not sid:
            return 0
        action = numbered_pick(
            console,
            [
                ("open", "open in chat"),
                ("show", "print transcript"),
                ("delete", "delete this session"),
            ],
            current="open",
            title=sid,
            noun="action",
        )
        if action == "open":
            args.session = sid
            if not getattr(args, "cwd", None):
                args.cwd = os.getcwd()
            for name, default in (
                ("provider", None),
                ("model", None),
                ("mode", "build"),
                ("approval", None),
                ("config", None),
                ("verbose", False),
            ):
                if not hasattr(args, name):
                    setattr(args, name, default)
            return cmd_chat(args)
        if action == "show":
            args.show = sid
            return cmd_sessions(args)
        if action == "delete":
            if not confirm(console, f"Delete {sid}?", default=False):
                console.print("[yellow]Cancelled[/]")
                return 130
            gone = delete_session(sid)
            extra = " + trajectory" if gone.trajectory else ""
            console.print(f"deleted {gone.id}{extra}")
            return 0
        return 0

    table = Table(title=f"Sessions in {kite_home() / 'sessions'}")
    table.add_column("id")
    table.add_column("model")
    table.add_column("status")
    table.add_column("label")
    for meta in rows:
        table.add_row(meta.id, f"{meta.provider}/{meta.model}", meta.exit_status or "-", meta.label[:50])
    console.print(table)
    return 0


def cmd_providers(_args: argparse.Namespace) -> int:
    from rich.table import Table

    from kite.config import UserConfig, assess_setup_status
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import configured_providers, provider_credential_status

    console = _console()
    catalog = load_catalog()
    cfg = UserConfig.load()
    status = assess_setup_status()
    cred_rows = {name: (ok, env) for name, ok, env in configured_providers()}
    table = Table(title="Providers")
    table.add_column("name")
    table.add_column("display")
    table.add_column("selected model")
    table.add_column("auth")
    table.add_column("status")
    for p in catalog.list():
        ok, env_col = cred_rows.get(p.name, (False, p.api_key_env or "—"))
        auth = env_col if env_col in {"local", "oauth", "—"} else (p.api_key_env or "—")
        cred_status = provider_credential_status(ok=ok, env_col=env_col)
        selected = (
            cfg.provider_defaults.get(p.name)
            or (cfg.default_model if p.name == cfg.default_provider else None)
            or p.default_model
            or "(live)"
        )
        mark = " *" if p.name == cfg.default_provider else ""
        table.add_row(p.name + mark, p.display_name, selected, auth, cred_status)
    console.print(table)
    console.print(
        "[dim]* = default · BYOK = API key · BYOS = oauth subscription (chatgpt/claude/grok)[/]"
    )
    if status.ready:
        console.print(f"[green]Ready[/]  {status.default_provider}/{status.default_model}")
    else:
        console.print("[yellow]Not ready[/] — run [cyan]kite setup[/] or [cyan]/setup[/] in the REPL")
        for hint in status.hints[:2]:
            console.print(f"[dim]{hint}[/]")
    from kite.ui.pick import can_prompt, numbered_pick

    if can_prompt():
        from kite.providers.select import connect_interactive

        picked = numbered_pick(
            console,
            [(p.name, f"{p.display_name}  ({p.name})") for p in catalog.list()],
            current=cfg.default_provider,
            title="Connect a provider (empty = done)",
            noun="provider",
        )
        if picked:
            code, _, _ = connect_interactive(
                console, provider=picked, persist=True, login_if_needed=True
            )
            return code
    return 0


def _select_model_interactive(console, provider: str) -> int:
    from kite.providers.select import connect_interactive

    code, _, _ = connect_interactive(console, provider=provider, persist=True, login_if_needed=True)
    return code


def cmd_models(args: argparse.Namespace) -> int:
    from rich.table import Table

    from kite.config import UserConfig
    from kite.providers.catalog import load_catalog
    from kite.providers.list_models import list_models_for_provider

    console = _console()
    cfg = UserConfig.load()
    catalog = load_catalog()

    from kite.ui.pick import can_prompt

    if args.select or (can_prompt() and not getattr(args, "list", False)):
        from kite.providers.list_models import clear_model_list_cache
        from kite.providers.select import connect_interactive

        if getattr(args, "refresh", False):
            clear_model_list_cache(args.provider)
        code, _, _ = connect_interactive(
            console,
            provider=args.provider,
            persist=True,
            login_if_needed=True,
        )
        return code

    if getattr(args, "refresh", False):
        from kite.providers.list_models import clear_model_list_cache

        clear_model_list_cache(args.provider)
    names = [args.provider] if args.provider else [p.name for p in catalog.list()]
    exit_code = 0
    for name in names:
        try:
            spec = catalog.get(name)
        except KeyError as e:
            console.print(f"[red]{e}[/]")
            exit_code = 1
            continue

        console.print(f"[dim]Fetching[/] {spec.display_name} ({spec.name})…")
        result = list_models_for_provider(
            spec,
            config=cfg,
            catalog=catalog,
            refresh=bool(getattr(args, "refresh", False)),
        )
        table = Table(title=f"{spec.display_name} ({spec.name}) — live")
        table.add_column("model")
        table.add_column("context")
        table.add_column("owned_by")
        table.add_column("litellm id")
        if result.error:
            console.print(f"[yellow]{result.error}[/]")
            exit_code = 1
            continue
        selected = cfg.provider_defaults.get(name) or (
            cfg.default_model if cfg.default_provider == name else None
        )
        for m in result.models:
            mark = " *" if selected and m.id == selected else ""
            ctx = str(m.context_window) if m.context_window else "—"
            table.add_row(
                m.id + mark,
                ctx,
                m.owned_by or "—",
                spec.litellm_model_id(m.id),
            )
        console.print(table)
        if selected:
            console.print("[dim]* = selected in ~/.kite/config.toml[/]")
    return exit_code


def cmd_config(args: argparse.Namespace) -> int:
    from rich.panel import Panel

    from kite.config import UserConfig, kite_home
    from kite.providers.resolve import missing_credentials, missing_model, resolve_model

    console = _console()
    cfg = UserConfig.load()
    if args.select_model:
        provider = args.set_provider or cfg.default_provider or "openai"
        return _select_model_interactive(console, provider)
    if args.set_provider:
        cfg.default_provider = args.set_provider
    if args.set_model:
        cfg.default_model = args.set_model
        if args.set_provider or cfg.default_provider:
            cfg.provider_defaults[args.set_provider or cfg.default_provider] = args.set_model
    if args.set_api_base:
        if not args.set_provider and not cfg.default_provider:
            console.print("[red]Need --set-provider with --set-api-base[/]")
            return 2
        cfg.api_bases[args.set_provider or cfg.default_provider] = args.set_api_base
    if args.auto_compact is not None:
        cfg.auto_compact = args.auto_compact
    if any([args.set_provider, args.set_model, args.set_api_base, args.auto_compact is not None]):
        path = cfg.save()
        console.print(f"[green]Saved[/] {path}")

    resolved = resolve_model(config=cfg)
    console.print(
        Panel(
            json.dumps(
                {
                    "home": str(kite_home()),
                    "default_provider": cfg.default_provider,
                    "default_model": cfg.default_model,
                    "resolved": {
                        "provider": resolved.provider,
                        "model": resolved.model,
                        "litellm": resolved.litellm_model,
                        "context_window": resolved.context_window,
                        "api_base": resolved.api_base,
                        "credentials": missing_credentials(resolved) or "ok",
                        "model_status": missing_model(resolved) or "ok",
                    },
                    "step_limit": cfg.step_limit,
                    "cost_limit": cfg.cost_limit,
                    "auto_compact": cfg.auto_compact,
                    "api_bases": cfg.api_bases,
                    "provider_defaults": cfg.provider_defaults,
                },
                indent=2,
            ),
            title="kite config",
        )
    )
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    from rich.panel import Panel

    from kite.config import UserConfig
    from kite.context.discovery import gather_project_context
    from kite.context.window import estimate_usage
    from kite.providers.resolve import resolve_model
    from kite.tools import ToolRegistry
    from kite.tools.coding import make_coding_tools

    console = _console()
    cfg = UserConfig.load()
    ctx = gather_project_context(
        args.cwd,
        include_git=cfg.include_git_status,
        include_tree=cfg.include_tree_snippet,
        tree_max_entries=cfg.tree_max_entries,
    )
    rendered = ctx.render_for_prompt()
    if args.json:
        console.print(
            json.dumps(
                {
                    "root": str(ctx.root),
                    "cwd": str(ctx.cwd),
                    "files": [f.path for f in ctx.files],
                    "chars": len(rendered),
                },
                indent=2,
            )
        )
        return 0
    console.print(Panel(rendered[:8_000] + ("…" if len(rendered) > 8_000 else ""), title="project context"))
    resolved = resolve_model(provider=args.provider, model=args.model, config=cfg)
    registry = ToolRegistry(make_coding_tools(cwd=args.cwd))
    usage = estimate_usage(
        system="stub",
        messages=[{"role": "user", "content": rendered}],
        tool_schemas=registry.openai_schemas(),
        window=resolved.context_window,
    )
    console.print(
        f"Estimated context tokens≈{usage.total_tokens} / window={usage.window} "
        f"(provider={resolved.provider} model={resolved.model})"
    )
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    from rich.panel import Panel
    from rich.table import Table

    console = _console()
    if getattr(args, "add", None):
        from kite.skills.install import install_skill

        try:
            names = install_skill(args.add)
        except (ValueError, RuntimeError, OSError) as e:
            console.print(f"[red]{e}[/]")
            return 1
        console.print(f"installed {', '.join(names)} → ~/.kite/skills")
        return 0
    from kite.skills.loader import load_skills

    skills = load_skills(args.cwd)
    if args.show:
        match = next((s for s in skills if s.name == args.show), None)
        if not match:
            console.print(f"[red]Unknown skill {args.show}[/]")
            return 1
        console.print(Panel(match.content, title=f"{match.name} — {match.path}"))
        return 0
    table = Table(title="Skills")
    table.add_column("name")
    table.add_column("description")
    table.add_column("path")
    for s in skills:
        label = f"{s.name} ~" if s.source == "user" else s.name
        table.add_row(label, (s.description or "")[:60], str(s.path))
    console.print(table)
    from kite.ui.pick import can_prompt, numbered_pick

    if can_prompt() and skills:
        picked = numbered_pick(
            console,
            [(s.name, f"{s.name}  {(s.description or '')[:50]}") for s in skills],
            current=None,
            title="Show a skill (empty = done)",
            noun="skill",
        )
        if picked:
            args.show = picked
            return cmd_skills(args)
    return 0


def cmd_commands(args: argparse.Namespace) -> int:
    from rich.table import Table

    from kite.cli.slash import CommandIndex

    console = _console()

    index = CommandIndex.load(args.cwd)
    table = Table(title="Slash commands")
    table.add_column("name")
    table.add_column("source")
    table.add_column("description")
    seen: set[str] = set()
    for spec in sorted(index.prompt_specs(), key=lambda s: (s.source, s.name)):
        if spec.name in seen:
            continue
        seen.add(spec.name)
        table.add_row(f"/{spec.name}", spec.plugin or spec.source, (spec.description or "")[:70])
    console.print(table)
    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    from rich.table import Table

    from kite.plugins.loader import load_plugins

    console = _console()

    plugins = load_plugins(args.cwd)
    if not plugins:
        console.print("No plugins. REPL: /plugins init name  ->  .kite/plugins/<name>")
        return 0
    table = Table(title="Plugins")
    table.add_column("name")
    table.add_column("source")
    table.add_column("commands")
    table.add_column("path")
    for plugin in plugins:
        table.add_row(plugin.name, plugin.source, str(len(plugin.commands)), str(plugin.path))
    console.print(table)
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    console = _console()
    from kite.memory.store import MemoryStore

    store = MemoryStore.open(args.cwd)
    if args.remember:
        scope = "project" if args.project else "user"
        note = store.remember(args.remember, scope=scope)
        console.print(f"remembered {note.scope}/{note.id}: {note.text}")
        return 0
    if args.forget:
        removed = store.forget(args.forget)
        if not removed:
            console.print("no matching notes")
            return 1
        for note in removed:
            console.print(f"forgot {note.scope}/{note.id}: {note.text}")
        return 0
    notes = store.notes()
    if not notes:
        console.print(f"(empty)  {store.user_notes_path()}")
        return 0
    for note in notes:
        console.print(f"{note.scope}/{note.id}  {note.text}")
    return 0


def cmd_runtime_config(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from rich.panel import Panel

    from kite.config import load_runtime_config

    console = _console()

    rcfg = load_runtime_config(args.config)
    console.print(Panel(json.dumps(asdict(rcfg), indent=2), title="runtime config"))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    from kite.cli.apply_cmd import apply_trajectory, apply_unified_diff

    console = _console()
    path = Path(args.path)
    if not path.is_file():
        console.print(f"[red]not found: {path}[/]")
        return 2
    if path.suffix == ".diff" or path.name.endswith(".patch"):
        result = apply_unified_diff(path.read_text(encoding="utf-8"), cwd=args.cwd, dry_run=args.dry_run)
    else:
        result = apply_trajectory(path, cwd=args.cwd, dry_run=args.dry_run)
    for line in result.get("applied") or []:
        console.print(f"[green]{'would ' if args.dry_run else ''}{line}[/]")
    for line in result.get("skipped") or []:
        console.print(f"[yellow]skipped: {line}[/]")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from kite.cli.import_cmd import import_session

    console = _console()
    try:
        session = import_session(args.format, Path(args.path), cwd=args.cwd, label=args.label or "")
    except (OSError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return 1
    console.print(f"[green]imported[/] session {session.id} ({len(session.messages)} messages)")
    console.print(f"[dim]resume with: kite resume {session.id}[/]")
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    args.approval = args.approval or "auto"
    if not getattr(args, "quiet", False) and not getattr(args, "verbose", False):
        args.quiet = True
    return cmd_run(args)


def cmd_audit(args: argparse.Namespace) -> int:
    from kite.memory.audit import AuditLog

    console = _console()
    rows = AuditLog().tail(args.limit)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        kind = row.get("kind", "?")
        ts = row.get("ts", "")
        payload = {k: v for k, v in row.items() if k not in {"ts", "kind"}}
        console.print(f"[dim]{ts:.0f}[/] [cyan]{kind}[/] {json.dumps(payload)}")
    return 0


def cmd_cloud(args: argparse.Namespace) -> int:
    from kite.config import kite_home

    console = _console()
    cloud_dir = kite_home() / "cloud"
    if args.action == "list":
        if not cloud_dir.is_dir():
            console.print("[dim]no cloud tasks — save trajectories to ~/.kite/cloud/<id>.json[/]")
            return 0
        for p in sorted(cloud_dir.glob("*.json")):
            console.print(p.stem)
        return 0
    if args.action == "apply":
        if not args.task_id:
            from kite.ui.pick import can_prompt, numbered_pick

            if not can_prompt() or not cloud_dir.is_dir():
                console.print("[red]task id required[/]")
                return 2
            files = sorted(cloud_dir.glob("*.json"))
            if not files:
                console.print("[dim]no cloud tasks[/]")
                return 1
            picked = numbered_pick(
                console,
                [(p.stem, p.name) for p in files],
                current=None,
                title="Apply a cloud task",
                noun="task",
            )
            if not picked:
                return 130
            args.task_id = picked
        path = cloud_dir / f"{args.task_id}.json"
        if not path.is_file():
            console.print(f"[red]not found: {path}[/]")
            return 1
        from kite.cli.apply_cmd import apply_trajectory

        result = apply_trajectory(path, cwd=args.cwd, dry_run=args.dry_run)
        console.print(f"applied {result.get('count', 0)} patch(es)")
        return 0
    console.print("[red]use: kite cloud list | kite cloud apply <id>[/]")
    return 2


def _add_run_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("-p", "--provider", help="Provider name from catalog")
    p.add_argument("-m", "--model", help="Model id within provider")
    p.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    p.add_argument("--config", help="Runtime config name or path (TOML)")
    p.add_argument("--steps", type=int, default=None, help="Max model calls")
    p.add_argument("--cost", type=float, default=None, help="Cost limit USD")
    p.add_argument("--time", type=int, default=0, help="Wall-time limit seconds")
    p.add_argument("-o", "--output", help="Trajectory JSON path")
    p.add_argument("--label", default="", help="Session label")
    p.add_argument("--no-context", action="store_true", help="Skip AGENTS.md/git/tree injection")
    p.add_argument("--no-compact", action="store_true", help="Disable auto context compaction")
    p.add_argument("--no-guardrails", action="store_true", help="Disable path/bash/secret guardrails")
    p.add_argument(
        "--attach",
        action="append",
        default=[],
        metavar="PATH",
        help="Attach a file or image to the task (repeatable)",
    )
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument(
        "--mode",
        choices=["plan", "build"],
        default="build",
        help="plan = read-only checklist; build = apply edits",
    )
    p.add_argument(
        "--approval",
        choices=["auto", "supervised", "yolo", "trust", "approve", "readonly"],
        default=None,
        help="Autonomy: auto | supervised (approve) | yolo | trust | readonly",
    )
    p.add_argument(
        "--role",
        choices=["auto", "architect", "implementer", "debugger"],
        default="auto",
        help="Agent persona — architect/debugger/implementer",
    )
    p.add_argument(
        "--long",
        action="store_true",
        help="Long-running agentic task: higher limits, phase checkpoints, mode_long prompt",
    )
    p.add_argument("--json", action="store_true", help="Emit final trajectory JSON on stdout (CI-friendly)")


def cmd_help(_args: argparse.Namespace) -> int:
    from kite.cli.help_map import cli_help_text

    print(cli_help_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    from kite.cli.help_map import CLI_EPILOG

    parser = argparse.ArgumentParser(
        prog="kite",
        description="Kite coding agent — plan or build in the terminal",
        epilog=CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="store_true", help="Print version")
    sub = parser.add_subparsers(dest="command")

    help_p = sub.add_parser("help", help="Print CLI quick reference")
    help_p.set_defaults(func=cmd_help)

    run = sub.add_parser("run", help="One-shot task")
    run.add_argument("task", nargs="?", help="Task prompt")
    run.add_argument("--stdin", action="store_true", help="Read task from stdin")
    _add_run_flags(run)
    run.set_defaults(func=cmd_run)

    chat = sub.add_parser("chat", help="Interactive REPL (default when bare `kite`)")
    _add_run_flags(chat)
    chat.add_argument("--session", help="Open an existing session id")
    chat.set_defaults(func=cmd_chat)

    resume = sub.add_parser("resume", help="Continue an existing session (omit id to pick)")
    resume.add_argument("session", nargs="?", help="Session id (omit to pick in a terminal)")
    resume.add_argument("message", nargs="?", help="Follow-up message")
    resume.add_argument("--task", help="Alias for follow-up message")
    _add_run_flags(resume)
    resume.set_defaults(func=cmd_resume)

    sessions = sub.add_parser("sessions", help="List or inspect saved sessions")
    sessions.add_argument("--limit", type=int, default=20)
    sessions.add_argument("--show", help="Show session id")
    sessions.add_argument("--tail", type=int, default=12, help="Messages to show with --show")
    sessions.add_argument(
        "--delete",
        nargs="+",
        metavar="ID",
        help="Delete session id(s) (prefix ok if unique)",
    )
    sessions.add_argument("--delete-all", action="store_true", help="Delete every saved session")
    sessions.add_argument("-y", "--yes", action="store_true", help="Confirm --delete-all")
    sessions.set_defaults(func=cmd_sessions)

    providers = sub.add_parser("providers", help="List providers + credential status")
    providers.set_defaults(func=cmd_providers)

    from kite.cli.setup import cmd_keys, cmd_login, cmd_setup
    from kite.cli.stats import cmd_maintainer_dashboard
    from kite.cli.dashboard import cmd_dashboard

    setup = sub.add_parser("setup", help="First-run wizard — credentials, provider, model")
    setup.add_argument("-p", "--provider", help="Skip provider picker")
    setup.set_defaults(func=cmd_setup)

    login = sub.add_parser(
        "login",
        help="Link provider — BYOK API key (hidden) or BYOS OAuth subscription",
    )
    login.add_argument("provider", nargs="?", help="Provider name (chatgpt, groq, claude, …)")
    login.add_argument(
        "--no-set-default",
        action="store_false",
        dest="set_default",
        help="Do not set this provider as default in ~/.kite/config.toml",
    )
    login.set_defaults(func=cmd_login, set_default=True)

    keys = sub.add_parser("keys", help="Show credential status or set a BYOK API key")
    keys.add_argument(
        "--set",
        nargs="?",
        const="",
        metavar="PROVIDER",
        help="Paste a key (omit provider to pick)",
    )
    keys.add_argument(
        "--logout",
        nargs="?",
        const="",
        metavar="PROVIDER",
        help="Remove a provider key or OAuth session (omit to pick)",
    )
    keys.set_defaults(func=cmd_keys)

    maintainer = sub.add_parser("maintainer", help=argparse.SUPPRESS)
    maint_sub = maintainer.add_subparsers(dest="maintainer_cmd")
    dashboard = maint_sub.add_parser("dashboard", help=argparse.SUPPRESS)
    dashboard.add_argument("--json", action="store_true")
    dashboard.set_defaults(func=cmd_maintainer_dashboard)

    models = sub.add_parser("models", help="Pick a live model (or --list to dump)")
    models.add_argument("-p", "--provider", help="Filter one provider")
    models.add_argument(
        "--select",
        action="store_true",
        help="Interactively pick a model and save it to ~/.kite/config.toml",
    )
    models.add_argument(
        "--list",
        action="store_true",
        help="Print the model table instead of opening the picker",
    )
    models.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass the model-list cache and re-fetch from the provider API",
    )
    models.set_defaults(func=cmd_models)

    config = sub.add_parser("config", help="Show or update ~/.kite/config.toml")
    config.add_argument("--set-provider", help="Set default provider")
    config.add_argument("--set-model", help="Set default model")
    config.add_argument(
        "--select-model",
        action="store_true",
        help="Fetch live models and interactively select one",
    )
    config.add_argument("--set-api-base", help="Override provider base URL")
    config.add_argument("--auto-compact", type=lambda s: s.lower() in {"1", "true", "yes"}, default=None)
    config.set_defaults(func=cmd_config)

    context = sub.add_parser("context", help="Preview discovered project context")
    context.add_argument("--cwd", default=os.getcwd())
    context.add_argument("-p", "--provider")
    context.add_argument("-m", "--model")
    context.add_argument("--json", action="store_true")
    context.set_defaults(func=cmd_context)

    skills = sub.add_parser("skills", help="List, show, or install markdown skills")
    skills.add_argument("--cwd", default=os.getcwd())
    skills.add_argument("--show", help="Show skill body by name")
    skills.add_argument("--add", help="Install from npm, npx, or GitHub owner/repo")
    skills.set_defaults(func=cmd_skills)

    commands = sub.add_parser("commands", help="List markdown slash commands + skills")
    commands.add_argument("--cwd", default=os.getcwd())
    commands.set_defaults(func=cmd_commands)

    plugins = sub.add_parser("plugins", help="List installed command/skill plugins")
    plugins.add_argument("--cwd", default=os.getcwd())
    plugins.set_defaults(func=cmd_plugins)

    memory = sub.add_parser("memory", help="Show or update durable notes")
    memory.add_argument("--cwd", default=os.getcwd())
    memory.add_argument("--remember", help="Add a note")
    memory.add_argument("--forget", help="Drop notes by id or substring")
    memory.add_argument("--project", action="store_true", help="With --remember, store on the project")
    memory.set_defaults(func=cmd_memory)

    rt = sub.add_parser("runtime-config", help="Show merged runtime TOML (advanced)")
    rt.add_argument("--config", help="Named config or path")
    rt.set_defaults(func=cmd_runtime_config)

    apply_p = sub.add_parser("apply", help="Apply a trajectory or diff patch to the working tree")
    apply_p.add_argument("path", help="Trajectory JSON or .diff/.patch file")
    apply_p.add_argument("--cwd", default=os.getcwd())
    apply_p.add_argument("--dry-run", action="store_true")
    apply_p.set_defaults(func=cmd_apply)

    imp = sub.add_parser("import", help="Import session history from another coding CLI")
    imp.add_argument("format", choices=["cursor", "claude", "claude-code", "aider", "codex", "kite"])
    imp.add_argument("path", help="Export file path")
    imp.add_argument("--cwd", default=os.getcwd())
    imp.add_argument("--label", default="")
    imp.set_defaults(func=cmd_import)

    exec_p = sub.add_parser("exec", help="CI one-shot (auto approval, quiet, optional --json)")
    exec_p.add_argument("task", nargs="?", help="Task prompt")
    exec_p.add_argument("--stdin", action="store_true")
    _add_run_flags(exec_p)
    exec_p.set_defaults(func=cmd_exec)

    audit = sub.add_parser("audit", help="Show governance audit log")
    audit.add_argument("--limit", type=int, default=30)
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(func=cmd_audit)

    dashboard = sub.add_parser("dashboard", help="Interactive harness stats — sessions, tools, tokens, cache")
    dashboard.add_argument("--session", help="Drill into one session id")
    dashboard.add_argument("--limit", type=int, default=200, help="Max sessions to scan")
    dashboard.add_argument("--watch", type=int, default=0, metavar="SEC", help="Refresh every N seconds")
    dashboard.add_argument("--json", action="store_true")
    dashboard.set_defaults(func=cmd_dashboard)

    cloud = sub.add_parser("cloud", help="Cloud/local task parity — list and apply saved outputs")
    cloud.add_argument("action", choices=["list", "apply"], nargs="?", default="list")
    cloud.add_argument("task_id", nargs="?", help="Task id for apply")
    cloud.add_argument("--cwd", default=os.getcwd())
    cloud.add_argument("--dry-run", action="store_true")
    cloud.set_defaults(func=cmd_cloud)

    from kite.cli.bench import add_bench_parser

    add_bench_parser(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw in (["--version"], ["-V"]):
        from kite import __version__

        print(__version__)
        return 0

    from kite.providers.credentials import load_kite_env

    load_kite_env()

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from kite import __version__

        print(__version__)
        return 0

    # Bare `kite` → interactive chat (cold-start REPL). `kite --help` still works.
    if args.command is None:
        from kite.ui.style import make_console

        from kite.cli.setup import maybe_run_first_setup

        console = make_console(stderr=True)
        setup_code = maybe_run_first_setup(console)
        if setup_code is not None:
            if setup_code != 0:
                return setup_code
        return cmd_chat(
            argparse.Namespace(
                provider=None,
                model=None,
                cwd=os.getcwd(),
                config=None,
                mode="build",
                approval=None,
                verbose=False,
            )
        )

    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
