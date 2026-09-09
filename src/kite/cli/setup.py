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
    login_provider,
    logout_provider,
    provider_credential_status,
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
]


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
            "[dim]REPL shortcuts: Ctrl+O expand tools · Ctrl+P plan · Ctrl+B build · /help[/]",
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
    from rich.table import Table

    from kite.config import UserConfig
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import (
        api_key_fingerprint,
        credential_type_label,
    logout_provider,
    )
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    env_path = env_file_path()
    catalog = load_catalog()
    cfg = UserConfig.load()
    rows = configured_providers()

    if getattr(args, "logout", None) is not None:
        provider = (args.logout or "").strip()
        if not provider:
            from kite.ui.pick import numbered_pick

            linked = [(name, f"{name}  {env}") for name, ok, env in rows if ok and env != "local"]
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

    table = Table(title="Provider credentials")
    table.add_column("provider")
    table.add_column("type")
    table.add_column("status")
    table.add_column("detail")
    for name, ok, env in rows:
        try:
            spec = catalog.get(name)
            kind = credential_type_label(spec)
        except KeyError:
            kind = "—"
            spec = None
        status = provider_credential_status(ok=ok, env_col=env)
        if kind == "BYOK" and ok and spec is not None:
            detail = api_key_fingerprint(spec) or env
        elif kind == "BYOS":
            detail = "oauth"
        elif env == "local":
            detail = "localhost"
        else:
            detail = env if env not in {"—"} else "—"

        if ok:
            status = f"[green]{status}[/]"
        elif kind == "BYOS":
            status = f"[yellow]{status}[/]"
        elif env not in {"local", "—"}:
            status = f"[yellow]{status}[/]"

        mark = " *" if name == cfg.default_provider else ""
        table.add_row(name + mark, kind, status, detail)

    console.print(table)
    console.print(
        f"[dim]BYOK keys:[/] {env_path}  "
        f"[dim]BYOS:[/] provider CLIs (~/.codex, Claude Code, ~/.grok)"
    )
    console.print(
        "[dim]Add:[/] [cyan]kite keys --set groq[/] (BYOK)  ·  "
        "[cyan]kite login codex|claude|grok[/] (BYOS)  ·  "
        "[cyan]kite logout <provider>[/]"
    )

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
        picked = numbered_pick(
            console,
            [(name, f"{name}  {env}") for name, _ok, env in rows],
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
        console.print(f"[dim]Ready[/]  [cyan]{resolved}/{model}[/]")
    return 0


def needs_model_after_key(provider: str) -> bool:
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
