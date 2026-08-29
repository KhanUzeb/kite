"""Kite CLI — run / resume / sessions / models / providers / config / context."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from kite.cli.display import make_run_display
from kite.config import UserConfig, ensure_home, kite_home
from kite.context.discovery import gather_project_context
from kite.context.window import estimate_usage
from kite.agent.harness import Harness, HarnessConfig
from kite.memory.session import list_sessions, load_session
from kite.agent.mode import AgentMode, ApprovalMode, default_approval
from kite.providers.catalog import load_catalog
from kite.providers.keys import api_key_for
from kite.providers.list_models import list_models_for_provider
from kite.providers.resolve import missing_credentials, missing_model, resolve_model
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools
from kite.ui.approval import make_approver
from kite.ui.git import GitCheckpoints, git_branch
from kite.ui.repl import ChatSession
from kite.ui.state import SessionUiState
from kite.ui.style import make_console


def _console() -> Console:
    return make_console(stderr=True)


def _event_printer(console: Console, *, quiet: bool, verbose: bool):
    """Backward-compatible name — delegates to the streaming RunDisplay. """
    return make_run_display(console, quiet=quiet, verbose=verbose)


def _parse_mode(raw: str | None) -> AgentMode:
    try:
        return AgentMode((raw or "build").lower())
    except ValueError:
        return AgentMode.BUILD


def _parse_approval(raw: str | None, mode: AgentMode) -> ApprovalMode:
    if raw:
        try:
            return ApprovalMode(raw.lower())
        except ValueError:
            return default_approval(mode)
    return ApprovalMode.AUTO if mode is AgentMode.BUILD else ApprovalMode.READONLY


def _wire_display(harness: Harness, console: Console, args: argparse.Namespace) -> SessionUiState:
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
        harness.approver = make_approver(
            console,
            mode=mode,
            approval=approval,
            interactive=sys.stdin.isatty() and not getattr(args, "quiet", False),
        )
    if mode is AgentMode.BUILD:
        harness.checkpoints = GitCheckpoints.open(getattr(args, "cwd", os.getcwd()))
    return state


def cmd_run(args: argparse.Namespace) -> int:
    console = _console()
    task = args.task
    if not task and not args.stdin:
        console.print("[red]Provide a task or --stdin[/]")
        return 2
    if args.stdin:
        task = sys.stdin.read().strip()
    if not task:
        console.print("[red]Empty task[/]")
        return 2

    mode = _parse_mode(args.mode)
    approval = _parse_approval(args.approval, mode)
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
        )
    )
    _wire_display(harness, console, args)
    try:
        result = harness.run(task)
    except Exception as e:
        console.print(f"[red]{e}[/]")
        return 1

    sid = harness.last_session.id if harness.last_session else ""
    console.print(
        f"[bold]exit[/]={result.get('exit_status')}  "
        f"[bold]session[/]={sid}  "
        f"trajectory={ensure_home() / 'trajectories' / f'{sid}.json'}"
    )
    return 0 if result.get("exit_status") == "Submitted" else 1


def cmd_chat(args: argparse.Namespace) -> int:
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
    )
    return session.run()


def cmd_resume(args: argparse.Namespace) -> int:
    console = _console()
    follow = args.message or args.task
    if not follow:
        console.print("[red]Provide a follow-up message[/]")
        return 2
    mode = _parse_mode(args.mode)
    approval = _parse_approval(args.approval, mode)
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
        )
    )
    _wire_display(harness, console, args)
    try:
        result = harness.run(follow)
    except Exception as e:
        console.print(f"[red]{e}[/]")
        return 1
    console.print(f"[bold]exit[/]={result.get('exit_status')}  session={args.session}")
    return 0 if result.get("exit_status") == "Submitted" else 1


def cmd_sessions(args: argparse.Namespace) -> int:
    console = _console()
    if args.show:
        session = load_session(args.show)
        console.print(Panel(json.dumps(session.meta.to_dict(), indent=2), title=session.id))
        for i, m in enumerate(session.messages[-args.tail :], 1):
            role = m.get("role")
            content = (m.get("content") or "")[:200].replace("\n", " ")
            console.print(f"[dim]{i}[/] [cyan]{role}[/] {content}")
        return 0

    rows = list_sessions(limit=args.limit)
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
    console = _console()
    catalog = load_catalog()
    cfg = UserConfig.load()
    table = Table(title="Providers")
    table.add_column("name")
    table.add_column("selected model")
    table.add_column("api_key_env")
    table.add_column("key?")
    table.add_column("docs")
    for p in catalog.list():
        key_ok = "—"
        if p.api_key_env:
            key_ok = "yes" if api_key_for(p) else "missing"
        elif p.name == "ollama":
            key_ok = "local"
        selected = (
            cfg.provider_defaults.get(p.name)
            or (cfg.default_model if p.name == cfg.default_provider else None)
            or p.default_model
            or "(live)"
        )
        mark = " *" if p.name == cfg.default_provider else ""
        table.add_row(p.name + mark, selected, p.api_key_env or "-", key_ok, p.docs_url[:40])
    console.print(table)
    console.print("[dim]* = default provider · models fetched live via API key[/]")
    return 0


def _select_model_interactive(console: Console, provider: str) -> int:
    cfg = UserConfig.load()
    catalog = load_catalog()
    try:
        catalog.get(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/]")
        return 2

    console.print(f"[dim]Fetching models for[/] [bold]{provider}[/]…")
    result = list_models_for_provider(provider, config=cfg, catalog=catalog)
    if result.error:
        console.print(f"[red]{result.error}[/]")
        return 1
    if not result.models:
        console.print("[red]No models available[/]")
        return 1

    table = Table(title=f"Select a {provider} model")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("model")
    table.add_column("context")
    table.add_column("owned_by")
    current = cfg.provider_defaults.get(provider) or (
        cfg.default_model if cfg.default_provider == provider else None
    )
    for i, m in enumerate(result.models, start=1):
        mark = " *" if current and m.id == current else ""
        ctx = str(m.context_window) if m.context_window else "—"
        table.add_row(str(i), m.id + mark, ctx, m.owned_by or "—")
    console.print(table)
    console.print("[dim]* = currently selected[/]")

    try:
        raw = console.input("Enter number (or model id): ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled[/]")
        return 130

    if not raw:
        console.print("[yellow]Cancelled[/]")
        return 130

    chosen: str | None = None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(result.models):
            chosen = result.models[idx - 1].id
    else:
        ids = {m.id for m in result.models}
        if raw in ids:
            chosen = raw
        else:
            # allow typing a known substring if unique
            hits = [m.id for m in result.models if raw.lower() in m.id.lower()]
            if len(hits) == 1:
                chosen = hits[0]

    if not chosen:
        console.print("[red]Invalid selection[/]")
        return 2

    cfg.default_provider = provider
    cfg.default_model = chosen
    cfg.provider_defaults[provider] = chosen
    path = cfg.save()
    console.print(f"[green]Selected[/] {provider}/{chosen}")
    console.print(f"[dim]Saved {path}[/]")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    console = _console()
    cfg = UserConfig.load()
    catalog = load_catalog()

    if args.select:
        provider = args.provider or cfg.default_provider or "openai"
        return _select_model_interactive(console, provider)

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
        result = list_models_for_provider(spec, config=cfg, catalog=catalog)
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
    console = _console()
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
        table.add_row(s.name, (s.description or "")[:60], str(s.path))
    console.print(table)
    return 0


def cmd_commands(args: argparse.Namespace) -> int:
    console = _console()
    from kite.cli.slash import CommandIndex

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
    console = _console()
    from kite.plugins.loader import load_plugins

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
    console = _console()
    from dataclasses import asdict

    from kite.config import load_runtime_config

    rcfg = load_runtime_config(args.config)
    console.print(Panel(json.dumps(asdict(rcfg), indent=2), title="runtime config"))
    return 0


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
        choices=["auto", "approve", "readonly"],
        default=None,
        help="Autonomy: auto (sandbox), approve (ask), readonly. Default: auto for run, approve for chat.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kite",
        description="Kite coding agent - plan or build in the terminal",
    )
    parser.add_argument("--version", action="store_true", help="Print version")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Start a new agent session")
    run.add_argument("task", nargs="?", help="Task prompt")
    run.add_argument("--stdin", action="store_true", help="Read task from stdin")
    _add_run_flags(run)
    run.set_defaults(func=cmd_run)

    chat = sub.add_parser("chat", help="Interactive session (plan/build, slash commands)")
    _add_run_flags(chat)
    chat.set_defaults(func=cmd_chat)

    resume = sub.add_parser("resume", help="Continue an existing session")
    resume.add_argument("session", help="Session id (or prefix)")
    resume.add_argument("message", nargs="?", help="Follow-up message")
    resume.add_argument("--task", help="Alias for follow-up message")
    _add_run_flags(resume)
    resume.set_defaults(func=cmd_resume)

    sessions = sub.add_parser("sessions", help="List or inspect sessions")
    sessions.add_argument("--limit", type=int, default=20)
    sessions.add_argument("--show", help="Show session id")
    sessions.add_argument("--tail", type=int, default=12, help="Messages to show with --show")
    sessions.set_defaults(func=cmd_sessions)

    providers = sub.add_parser("providers", help="List providers + credential status")
    providers.set_defaults(func=cmd_providers)

    models = sub.add_parser("models", help="List live models from provider APIs (uses your API key)")
    models.add_argument("-p", "--provider", help="Filter one provider")
    models.add_argument(
        "--select",
        action="store_true",
        help="Interactively pick a model and save it to ~/.kite/config.toml",
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

    skills = sub.add_parser("skills", help="List or show markdown skills")
    skills.add_argument("--cwd", default=os.getcwd())
    skills.add_argument("--show", help="Show skill body by name")
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

    rt = sub.add_parser("runtime-config", help="Show merged agent runtime TOML config")
    rt.add_argument("--config", help="Named config or path")
    rt.set_defaults(func=cmd_runtime_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    # also load ~/.kite/.env if present
    env_file = kite_home() / ".env"
    if env_file.is_file():
        load_dotenv(env_file)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from kite import __version__

        print(__version__)
        return 0

    # Bare `kite` → interactive chat (cold-start REPL). `kite --help` still works.
    if args.command is None:
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
