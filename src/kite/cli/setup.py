"""First-run setup — API keys, provider, and model selection."""

from __future__ import annotations

from kite.config import UserConfig, kite_home
from kite.providers.credentials import (
    configured_providers,
    env_file_path,
    login_provider,
    write_api_key,
)
from kite.providers.catalog import load_catalog
from kite.providers.keys import api_key_env_names, api_key_for
from kite.providers.select import select_model_interactive, select_provider_interactive

# Re-export for tests and legacy imports.
__all__ = [
    "configured_providers",
    "env_file_path",
    "write_api_key",
    "cmd_setup",
    "cmd_keys",
]


def cmd_setup(args) -> int:
    from rich.panel import Panel

    from kite.ui.style import make_console

    console = make_console(stderr=True)
    env_path = env_file_path()

    console.print(
        Panel(
            "[bold]Welcome to Kite[/]\n\n"
            "This wizard helps you:\n"
            "  1. Add an API key to [cyan]~/.kite/.env[/] (owner-only permissions)\n"
            "  2. Pick a provider and model\n"
            "  3. Start chatting with [cyan]kite[/]\n\n"
            "In the REPL later: [cyan]/login provider[/]  [cyan]/keys[/]  [cyan]/logout provider[/]\n\n"
            f"Config: [dim]{UserConfig.load().path}[/]\n"
            f"Keys:   [dim]{env_path}[/]",
            title="kite setup",
            border_style="cyan",
        )
    )

    rows = configured_providers()
    ready = [name for name, ok, _ in rows if ok or name == "ollama"]
    if ready:
        console.print(f"[green]Keys found[/] for: {', '.join(ready)}")
    else:
        console.print("[yellow]No API keys detected yet[/]")

    provider = getattr(args, "provider", None) or select_provider_interactive(console)
    if not provider:
        console.print("[dim]Run [cyan]kite setup[/] or [cyan]/login provider[/] when ready.[/]")
        return 130

    catalog = load_catalog()
    try:
        spec = catalog.get(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/]")
        return 2

    if provider != "ollama" and spec.api_key_env and not api_key_for(spec):
        code, msg, _ = login_provider(provider, set_default=True, console=console)
        if code == 130:
            return 130
        if code != 0:
            console.print(f"[yellow]{msg}[/]")
        else:
            console.print(f"[green]{msg}[/]")

    code, picked_provider, model = select_model_interactive(console, provider, persist=True)
    if code != 0 or not picked_provider or not model:
        return code or 130

    console.print(
        Panel(
            "[green]You're ready.[/]\n\n"
            f"  [cyan]kite[/]              interactive chat in this folder\n"
            f"  [cyan]kite run \"…\"[/]     one-shot task\n"
            f"  [cyan]/login groq[/]      add or rotate a key anytime\n"
            f"  [cyan]/keys[/]            see what's set\n\n"
            "[dim]REPL shortcuts: Ctrl+O expand tools · Ctrl+P plan · Ctrl+B build · /help[/]",
            title="next steps",
            border_style="green",
        )
    )
    return 0


def cmd_keys(args) -> int:
    from rich.table import Table

    from kite.providers.credentials import logout_provider
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    env_path = env_file_path()

    if getattr(args, "logout", None):
        code, msg = logout_provider(args.logout)
        style = "green" if code == 0 else "red"
        console.print(f"[{style}]{msg}[/]")
        return code

    rows = configured_providers()
    table = Table(title="API keys")
    table.add_column("provider")
    table.add_column("status")
    table.add_column("env var")
    for name, ok, env in rows:
        if env == "local":
            status = "local"
        elif env == "—":
            status = "n/a"
        else:
            status = "[green]set[/]" if ok else "[yellow]missing[/]"
        table.add_row(name, status, env)

    console.print(table)
    console.print(f"[dim]File:[/] {env_path}  [dim](owner read/write only)[/]")
    console.print("[dim]Add:[/] [cyan]kite keys --set groq[/]  or  [cyan]/login groq[/] in the REPL")

    if getattr(args, "set", None):
        code, msg, _ = login_provider(args.set, set_default=False, console=console)
        if code == 130:
            console.print("\n[yellow]Cancelled[/]")
            return 130
        if code != 0:
            console.print(f"[red]{msg}[/]")
            return code
        console.print(f"[green]{msg}[/]")
    return 0
