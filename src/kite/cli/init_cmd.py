"""`kite init` — scaffold AGENTS.md / KITE.md or open the init skill in chat."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def cmd_init(args: argparse.Namespace) -> int:
    from kite.context.project_init import format_init_summary, scaffold_project_docs
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    directory = getattr(args, "directory", ".") or "."
    force = bool(getattr(args, "force", False))
    agents_only = bool(getattr(args, "agents_only", False))
    kite_only = bool(getattr(args, "kite_only", False))
    if agents_only and kite_only:
        console.print("[kite.error]use at most one of --agents-only and --kite-only[/]")
        return 2

    write_agents = not kite_only
    write_kite = not agents_only

    if getattr(args, "chat", False):
        return _launch_init_chat(directory, console)

    result = scaffold_project_docs(
        directory,
        write_agents=write_agents,
        write_kite=write_kite,
        force=force,
    )
    console.print(format_init_summary(result))
    if result.agents and result.agents.action == "skipped":
        console.print("[kite.pending]AGENTS.md already exists[/]  use --force to overwrite (creates .bak)")
    if result.kite and result.kite.action == "skipped":
        console.print("[kite.pending]KITE.md already exists[/]  use --force to overwrite (creates .bak)")
    return 0


def _launch_init_chat(directory: str, console) -> int:
    from kite.ui.repl import ChatSession

    cwd = str(Path(directory).expanduser().resolve())
    if not Path(cwd).is_dir():
        console.print(f"[kite.error]not a directory[/]  {cwd}")
        return 2
    session = ChatSession(
        cwd=cwd,
        initial_prompt=(
            "Load the `init` skill and bootstrap this workspace: generate or update root "
            "AGENTS.md from repo evidence. Ask before overwriting an existing AGENTS.md."
        ),
    )
    return session.run()


def add_init_parser(sub) -> None:
    init_p = sub.add_parser(
        "init",
        help="Scaffold AGENTS.md (and KITE.md) or run the init skill in chat",
    )
    init_p.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Project directory (default: current directory)",
    )
    init_p.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing files (backup as NAME.bak.<unix-ts>)",
    )
    init_p.add_argument(
        "--agents-only",
        action="store_true",
        help="Write AGENTS.md only",
    )
    init_p.add_argument(
        "--kite-only",
        action="store_true",
        help="Write KITE.md stub only",
    )
    init_p.add_argument(
        "--chat",
        action="store_true",
        help="Open interactive chat with the init skill prompt (like mcode init)",
    )
    init_p.set_defaults(func=cmd_init, cwd=os.getcwd())
