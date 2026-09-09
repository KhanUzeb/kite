"""List, show, and scaffold user subagent personas."""

from __future__ import annotations

from kite.agent.subagent_profiles import (
    format_profile_trust,
    get_profile,
    init_user_profile,
    list_profiles,
    profile_source_path,
    reload_profiles,
    user_profiles_dir,
)


def _console():
    from kite.ui.style import make_console

    return make_console(stderr=True)


def cmd_subagents(args) -> int:
    from rich.panel import Panel

    from kite.ui.pick import can_prompt, numbered_pick
    from kite.ui.tables import kite_table

    console = _console()
    reload_profiles()

    if getattr(args, "init", None):
        try:
            path = init_user_profile(
                args.init,
                label=getattr(args, "label", "") or "",
                role=getattr(args, "role", "auto") or "auto",
                description=getattr(args, "description", "") or "",
                force=bool(getattr(args, "force", False)),
            )
        except (ValueError, FileExistsError, OSError) as e:
            console.print(f"[red]{e}[/]")
            return 2
        console.print(f"[green]wrote[/] {path}")
        console.print("[dim]edit the markdown, then dispatch with profile=<id> on the subagent tool[/]")
        return 0

    profiles = list_profiles()
    if getattr(args, "show", None):
        match = get_profile(args.show)
        if match is None:
            console.print(f"[red]unknown profile {args.show}[/]")
            return 1
        src = profile_source_path(match)
        trust = format_profile_trust(match)
        header = (
            f"{match.id} — {match.label}  ·  role={match.role}  ·  trust={trust}"
            + (f"\n{src}" if src else "")
        )
        body = match.prompt
        if not match.bundled:
            body = match.compose("").split("## Task", 1)[0].strip()
            if body.startswith("# Subagent:"):
                body = "\n".join(body.split("\n", 1)[1:]).strip()
        console.print(Panel(body or "(empty prompt)", title=header))
        return 0

    table = kite_table("subagent profiles")
    table.add_column("id")
    table.add_column("label")
    table.add_column("role")
    table.add_column("trust")
    table.add_column("description")
    for p in profiles:
        mark = f"{p.id} ~" if not p.bundled else p.id
        desc = p.description or p.prompt.split("\n", 1)[0][:50]
        table.add_row(mark, p.label, p.role, format_profile_trust(p), desc)
    console.print(table)
    console.print(f"[dim]custom[/]  {user_profiles_dir()}/*.md")
    console.print("[dim]kite subagents --init my-role  ·  /agents init my-role[/]")

    if can_prompt() and profiles:
        picked = numbered_pick(
            console,
            [(p.id, f"{p.id}  {p.label}  ({format_profile_trust(p)})") for p in profiles],
            current=None,
            title="Show a profile (empty = done)",
            noun="profile",
        )
        if picked:
            args.show = picked
            return cmd_subagents(args)
    return 0


def add_subagents_parser(sub) -> None:
    p = sub.add_parser(
        "subagents",
        help="List, show, or scaffold subagent personas (bundled + ~/.kite/subagents/)",
    )
    p.add_argument("--show", metavar="ID", help="Show one persona by id")
    p.add_argument("--init", metavar="ID", help="Write ~/.kite/subagents/<id>.md stub")
    p.add_argument("--label", default="", help="With --init, display label in frontmatter")
    p.add_argument("--role", default="auto", help="With --init, role hint (architect|implementer|debugger|auto)")
    p.add_argument("--description", default="", help="With --init, one-line description")
    p.add_argument("--force", action="store_true", help="Overwrite existing user profile")
    p.set_defaults(func=cmd_subagents)
