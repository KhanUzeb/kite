"""First-run setup — API keys, provider, and model selection."""

from __future__ import annotations

from kite.config import UserConfig
from kite.config.readiness import (
    RECOMMENDED_PROVIDERS,
    assess_setup_status,
    config_path,
    is_fresh_install,
    offer_setup_interactive,
)
from kite.providers.byos import is_oauth_provider
from kite.providers.catalog import load_catalog
from kite.providers.credentials import (
    configured_providers,
    env_file_path,
    inspect_provider_credentials,
    login_provider,
    logout_provider,
    write_api_key,
)
from kite.providers.select import connect_interactive, select_provider_interactive

# Re-export for tests and legacy imports.
__all__ = [
    "configured_providers",
    "env_file_path",
    "write_api_key",
    "cmd_setup",
    "cmd_keys",
    "cmd_login",
    "cmd_logout",
    "run_setup_wizard",
    "maybe_run_first_setup",
    "print_providers_table",
    "print_keys_table",
]


NARROW_PROVIDER_WIDTH = 72


def _selected_model(cfg: UserConfig, spec) -> str:
    return (
        cfg.provider_defaults.get(spec.name)
        or (cfg.default_model if spec.name == cfg.default_provider else None)
        or spec.default_model
        or "(live)"
    )


def print_providers_table(console) -> None:
    from rich.table import Table

    from kite.providers.catalog import load_catalog

    catalog = load_catalog()
    cfg = UserConfig.load()
    narrow = console.size.width < NARROW_PROVIDER_WIDTH
    table = Table(title="Providers", expand=True, pad_edge=False)
    table.add_column("provider", no_wrap=True, overflow="ellipsis")
    table.add_column("model", no_wrap=True, overflow="ellipsis")
    table.add_column("status", no_wrap=True, overflow="ellipsis")
    if not narrow:
        table.add_column("display", no_wrap=True, overflow="ellipsis")
        table.add_column("auth", no_wrap=True, overflow="ellipsis")
    extras: list[str] = []
    for spec in catalog.list():
        cred = inspect_provider_credentials(spec)
        mark = " *" if spec.name == cfg.default_provider else ""
        provider = spec.name + mark
        model = _selected_model(cfg, spec)
        if narrow:
            table.add_row(provider, model, cred.detail)
            extras.append(f"  {spec.name}  {spec.display_name}  ·  {cred.method}")
        else:
            table.add_row(provider, model, cred.detail, spec.display_name, cred.method)
    console.print(table)
    if narrow:
        for line in extras:
            console.print(f"[dim]{line}[/]")
    console.print(
        "[dim]* = default · BYOK = API key · BYOS = oauth subscription (chatgpt/claude/grok)[/]"
    )


def print_keys_table(console) -> None:
    from rich.table import Table

    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import api_key_fingerprint, credential_type_label

    catalog = load_catalog()
    cfg = UserConfig.load()
    narrow = console.size.width < NARROW_PROVIDER_WIDTH
    table = Table(title="Keys", expand=True, pad_edge=False)
    table.add_column("provider", no_wrap=True, overflow="ellipsis")
    table.add_column("status", no_wrap=True, overflow="ellipsis")
    if not narrow:
        table.add_column("type", no_wrap=True, overflow="ellipsis")
        table.add_column("detail", no_wrap=True, overflow="ellipsis")
    extras: list[str] = []
    for spec in catalog.list():
        cred = inspect_provider_credentials(spec)
        kind = credential_type_label(spec)
        mark = " *" if spec.name == cfg.default_provider else ""
        if kind == "BYOK" and cred.usable:
            detail = api_key_fingerprint(spec) or cred.method
        elif kind == "BYOS":
            detail = cred.detail
        elif cred.method == "local":
            detail = "localhost"
        else:
            detail = cred.method
        status = cred.detail
        if cred.usable:
            status = f"[green]{status}[/]"
        elif kind == "BYOS":
            status = f"[yellow]{status}[/]"
        elif cred.method not in {"local", "—"}:
            status = f"[yellow]{status}[/]"
        if narrow:
            table.add_row(spec.name + mark, status)
            extras.append(f"  {spec.name}  {kind}  ·  {detail}")
        else:
            table.add_row(spec.name + mark, status, kind, detail)
    console.print(table)
    if narrow:
        for line in extras:
            console.print(f"[dim]{line}[/]")


def run_setup_wizard(console, *, provider: str | None = None) -> int:
    """Interactive setup — provider, key, model. Returns exit code."""
    from rich.panel import Panel

    env_path = env_file_path()
    status = assess_setup_status()

    if status.ready and not is_fresh_install():
        console.print(
            Panel(
                f"[green]Already configured[/]\n\n"
                f"  Provider: [cyan]{status.default_provider}[/]\n"
                f"  Model:    [cyan]{status.default_model or '(live default)'}[/]\n\n"
                "[dim]Change anytime: /model select · /login provider · kite keys[/]",
                title="kite setup",
                border_style="green",
            )
        )
        return 0

    console.print(
        Panel(
            "[bold]Welcome to Kite[/]\n\n"
            "Choose how you connect to a model:\n"
            "  · [cyan]BYOK[/] — API key (groq, openai, anthropic, …) → [cyan]~/.kite/.env[/]\n"
            "  · [cyan]BYOS[/] — subscription auth via Codex / Claude Code / Grok CLI\n\n"
            "This wizard will:\n"
            "  1. Link credentials for your provider\n"
            "  2. Pick a provider and model (BYOK: live list; BYOS: plan default)\n"
            "  3. Start chatting with [cyan]kite[/]\n\n"
            "[dim]Recommended free/local:[/] "
            + " · ".join(f"[cyan]{p}[/]" for p in RECOMMENDED_PROVIDERS)
            + "\n"
            "[dim]Subscriptions:[/] [cyan]chatgpt[/] · [cyan]claude[/] · [cyan]grok[/]\n\n"
            "Later: [cyan]/login provider[/]  [cyan]kite login provider[/]  [cyan]/keys[/]\n\n"
            f"Config: [dim]{config_path()}[/]\n"
            f"Keys:   [dim]{env_path}[/]",
            title="kite setup",
            border_style="cyan",
        )
    )

    rows = configured_providers()
    ready = [name for name, ok, _ in rows if ok]
    if ready:
        console.print(f"[green]Credentials ready[/] for: {', '.join(ready)}")
    else:
        console.print("[yellow]No credentials linked yet[/]")
        console.print(
            "[dim]Tip:[/] [cyan]groq[/] has a generous free tier (BYOK), or link "
            "[cyan]chatgpt[/]/[cyan]claude[/]/[cyan]grok[/] (BYOS subscription)."
        )

    picked = provider or select_provider_interactive(console, oauth_first=True)
    if not picked:
        console.print("[dim]Run [cyan]kite setup[/] or [cyan]/setup[/] in the REPL when ready.[/]")
        return 130

    code, picked_provider, model = connect_interactive(
        console, provider=picked, persist=True, login_if_needed=True, oauth_first=True
    )
    if code != 0 or not picked_provider or not model:
        return code or 130

    final = assess_setup_status(provider=picked_provider, model=model)
    if not final.ready:
        for blocker in final.blockers:
            console.print(f"[yellow]{blocker}[/]")
        return 1

    console.print(
        Panel(
            "[green]You're ready.[/]\n\n"
            "  [cyan]kite[/]              interactive chat in this folder\n"
            "  [cyan]kite run \"…\"[/]     one-shot task\n"
            "  [cyan]/login groq[/]      BYOK key or BYOS OAuth\n"
            "  [cyan]kite login chatgpt[/] link a subscription plan\n"
            "  [cyan]/keys[/]            see credential status\n\n"
            "[dim]REPL shortcuts: Ctrl+B build (default) · Ctrl+P plan (opt-in) · Ctrl+O expand · /help[/]",
            title="next steps",
            border_style="green",
        )
    )
    return 0


def cmd_setup(args) -> int:
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    provider = getattr(args, "provider", None)
    return run_setup_wizard(console, provider=provider)


def maybe_run_first_setup(console) -> int | None:
    """Offer setup on first bare `kite` launch. Returns exit code if setup ran, else None."""
    if not offer_setup_interactive(console):
        return None
    return run_setup_wizard(console)


def cmd_keys(args) -> int:
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import logout_provider
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    env_path = env_file_path()
    catalog = load_catalog()

    if getattr(args, "logout", None) is not None:
        provider = (args.logout or "").strip()
        if not provider:
            from kite.ui.pick import numbered_pick

            linked = []
            for spec in catalog.list():
                cred = inspect_provider_credentials(spec)
                if cred.linked and cred.method != "local":
                    linked.append((spec.name, f"{spec.name}  {cred.detail}"))
            if not linked:
                console.print("[yellow]No linked providers to log out[/]")
                return 1
            provider = numbered_pick(
                console, linked, current=None, title="Log out a provider", noun="provider"
            )
            if not provider:
                return 130
        code, msg = logout_provider(provider)
        style = "green" if code == 0 else "red"
        console.print(f"[{style}]{msg}[/]")
        return code

    print_keys_table(console)
    console.print(
        f"[dim]BYOK keys:[/] {env_path}  "
        f"[dim]BYOS:[/] provider CLIs (~/.codex, Claude Code, ~/.grok)"
    )
    console.print(
        "[dim]Add:[/] [cyan]kite keys --set groq[/] (BYOK)  ·  "
        "[cyan]kite web-keys set tavily|exa|firecrawl[/] (web)  ·  "
        "[cyan]kite login codex|claude|grok[/] (BYOS)  ·  "
        "[cyan]kite logout <provider>[/]"
    )
    from kite.cli.web_keys import print_web_keys_status

    print_web_keys_status(console)

    status = assess_setup_status()
    if status.ready:
        console.print(f"[green]Ready[/]  {status.default_provider}/{status.default_model}")
    else:
        console.print("[yellow]Not ready yet[/] — run [cyan]kite setup[/] or [cyan]/setup[/]")
        for hint in status.hints[:2]:
            console.print(f"[dim]{hint}[/]")

    if getattr(args, "set", None) is not None:
        provider = (args.set or "").strip()
        if not provider:
            from kite.providers.select import select_provider_interactive

            provider = select_provider_interactive(console) or ""
            if not provider:
                return 130
        code, msg, _ = login_provider(provider, set_default=False, console=console)
        if code == 130:
            console.print("\n[yellow]Cancelled[/]")
            return 130
        if code != 0:
            console.print(f"[red]{msg}[/]")
            return code
        console.print(f"[green]{msg}[/]")
        if needs_model_after_key(provider):
            console.print(f"[dim]Next:[/] [cyan]kite models -p {provider} --select[/]")
        return 0

    from kite.ui.pick import can_prompt, numbered_pick

    if can_prompt():
        cfg = UserConfig.load()
        picked = numbered_pick(
            console,
            [
                (spec.name, f"{spec.name}  {inspect_provider_credentials(spec).detail}")
                for spec in catalog.list()
            ],
            current=cfg.default_provider,
            title="Link a provider (empty = done)",
            noun="provider",
        )
        if picked:
            code, msg, _ = login_provider(picked, set_default=False, console=console)
            if code == 130:
                console.print("\n[yellow]Cancelled[/]")
                return 130
            if code != 0:
                console.print(f"[red]{msg}[/]")
                return code
            console.print(f"[green]{msg}[/]")
            if needs_model_after_key(picked):
                console.print(f"[dim]Next:[/] [cyan]kite models -p {picked}[/]")
    return 0


def cmd_logout(args) -> int:
    """Unlink a BYOS subscription via provider-supported logout."""
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    provider = (getattr(args, "provider", None) or "").strip()
    if not provider:
        from kite.providers.select import select_provider_interactive

        provider = select_provider_interactive(console, oauth_first=True) or ""
        if not provider:
            return 130
    code, msg = logout_provider(provider, byos_aliases=True)
    style = "green" if code == 0 else "red"
    console.print(f"[{style}]{msg}[/]")
    return code


def cmd_login(args) -> int:
    """Link BYOK API key or BYOS OAuth subscription, then pick a model."""
    from kite.providers.select import connect_interactive
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    code, resolved, model = connect_interactive(
        console,
        provider=getattr(args, "provider", None),
        oauth_first=True,
        persist=getattr(args, "set_default", True),
        force_login=True,
    )
    if code == 130:
        return 130
    if code != 0:
        return code
    if resolved and model:
        from kite.config.readiness import assess_setup_status

        status = assess_setup_status(provider=resolved, model=model)
        if status.ready:
            console.print(f"[dim]Ready[/]  [cyan]{resolved}/{model}[/]")
        else:
            for blocker in status.blockers:
                console.print(f"[yellow]{blocker}[/]")
    return 0


def needs_model_after_key(provider: str) -> bool:
    from kite.tools.web_providers import resolve_web_tool_env

    if resolve_web_tool_env(provider):
        return False
    catalog = load_catalog()
    try:
        spec = catalog.get(provider)
    except KeyError:
        return True
    if is_oauth_provider(spec):
        return False
    cfg = UserConfig.load()
    if cfg.default_model and cfg.default_provider == provider:
        return False
    if cfg.provider_defaults.get(provider):
        return False
    return True
