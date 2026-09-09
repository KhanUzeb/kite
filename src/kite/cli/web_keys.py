"""CLI for optional paid web-tool API keys (Tavily / Exa / Firecrawl).

Keys are stored in ~/.kite/.env with the same owner-only permissions as BYOK
provider keys. Also available via: kite keys --set tavily|exa|firecrawl
"""

from __future__ import annotations

from kite.providers.credentials import (
    configured_web_tool_keys,
    env_file_path,
    login_web_tool_key,
    logout_web_tool_key,
    web_tool_key_fingerprint,
)
from kite.tools.web_providers import SEARCH_AUTO_ORDER, WEB_TOOL_ENVS


def _console():
    from kite.ui.style import make_console

    return make_console(stderr=True)


def print_web_keys_status(console) -> None:
    from rich.table import Table

    table = Table(title="Web tool keys")
    table.add_column("name")
    table.add_column("env")
    table.add_column("status")
    table.add_column("detail")
    for name, ok, env_var in configured_web_tool_keys():
        if ok:
            status = "[green]set[/]"
            detail = web_tool_key_fingerprint(name) or env_var
        else:
            status = "[yellow]missing[/]"
            detail = env_var
        table.add_row(name, env_var, status, detail)
    console.print(table)
    console.print(f"[dim]Stored in[/] {env_file_path()}  [dim](owner-only perms)[/]")
    order = " → ".join(SEARCH_AUTO_ORDER)
    console.print(f"[dim]websearch auto order:[/] {order}")
    console.print(
        "[dim]Add:[/] [cyan]kite web-keys set tavily|exa|firecrawl[/]  ·  "
        "[cyan]kite keys --set tavily[/]  ·  "
        "[cyan]kite web-keys logout <name>[/]"
    )


def _pick_web_key(console, *, title: str, only_set: bool = False) -> str | None:
    from kite.ui.pick import numbered_pick

    rows = configured_web_tool_keys()
    choices = [
        (name, f"{name}  {env}" + ("  (set)" if ok else ""))
        for name, ok, env in rows
        if (ok if only_set else True)
    ]
    if not choices:
        return None
    return numbered_pick(console, choices, current=None, title=title, noun="web key")


def cmd_web_keys(args) -> int:
    console = _console()
    action = (getattr(args, "web_keys_cmd", None) or "status").strip().lower()

    if action in {"", "status", "list"}:
        print_web_keys_status(console)
        return 0

    if action == "set":
        name = (getattr(args, "name", None) or "").strip().lower()
        if not name:
            name = _pick_web_key(console, title="Set a web tool key") or ""
            if not name:
                return 130
        if name not in WEB_TOOL_ENVS:
            known = ", ".join(sorted(WEB_TOOL_ENVS))
            console.print(f"[red]unknown web key '{name}' — try: {known}[/]")
            return 2
        code, msg, _ = login_web_tool_key(name, console=console)
        if code == 130:
            console.print("\n[yellow]Cancelled[/]")
            return 130
        style = "green" if code == 0 else "red"
        console.print(f"[{style}]{msg}[/]")
        return code

    if action in {"logout", "unset", "remove"}:
        name = (getattr(args, "name", None) or "").strip().lower()
        if not name:
            name = _pick_web_key(console, title="Remove a web tool key", only_set=True) or ""
            if not name:
                console.print("[yellow]No web tool keys to remove[/]")
                return 1
        code, msg = logout_web_tool_key(name)
        style = "green" if code == 0 else "red"
        console.print(f"[{style}]{msg}[/]")
        return code

    console.print(f"[red]unknown action '{action}' — try: status | set | logout[/]")
    return 2


def add_web_keys_parser(sub) -> None:
    p = sub.add_parser(
        "web-keys",
        aliases=["web_keys"],
        help="Show or set optional web tool API keys (Tavily / Exa / Firecrawl)",
    )
    web_sub = p.add_subparsers(dest="web_keys_cmd")

    st = web_sub.add_parser("status", aliases=["list"], help="Show which web keys are set")
    st.set_defaults(func=cmd_web_keys)

    set_p = web_sub.add_parser("set", help="Paste and save a web tool key (hidden)")
    set_p.add_argument(
        "name",
        nargs="?",
        help="tavily | exa | firecrawl (omit to pick)",
    )
    set_p.set_defaults(func=cmd_web_keys)

    out = web_sub.add_parser(
        "logout",
        aliases=["unset", "remove"],
        help="Remove a web tool key from ~/.kite/.env",
    )
    out.add_argument(
        "name",
        nargs="?",
        help="tavily | exa | firecrawl (omit to pick)",
    )
    out.set_defaults(func=cmd_web_keys)

    p.set_defaults(func=cmd_web_keys, web_keys_cmd="status")
