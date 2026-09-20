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

    if getattr(args, "chat", False):
        return _launch_init_chat(directory, console)

    agents_only = bool(getattr(args, "agents_only", False))
    kite_only = bool(getattr(args, "kite_only", False))
    if agents_only and kite_only:
        console.print("[kite.error]use at most one of --agents-only and --kite-only[/]")
        return 2

    result = scaffold_project_docs(
        directory,
        write_agents=not kite_only,
        write_kite=not agents_only,
        force=bool(getattr(args, "force", False)),
    )
    console.print(format_init_summary(result))
    for label, wr in (("AGENTS.md", result.agents), ("KITE.md", result.kite)):
        if wr and wr.action == "skipped":
            console.print(f"[kite.pending]{label} exists[/]  use --force to overwrite")
    return 0


def _launch_init_chat(directory: str, console) -> int:
    from kite.ui.repl import ChatSession

    cwd = str(Path(directory).expanduser().resolve())
    if not Path(cwd).is_dir():
        console.print(f"[kite.error]not a directory[/]  {cwd}")
        return 2
    session = ChatSession(
        cwd=cwd,
        initial_prompt="Load the `init` skill and bootstrap root AGENTS.md for this workspace.",
    )
    return session.run()


def add_init_parser(sub) -> None:
    init_p = sub.add_parser("init", help="Scaffold AGENTS.md (+ KITE.md) or run init skill in chat")
    init_p.add_argument("directory", nargs="?", default=".", help="Project directory")
    init_p.add_argument("-f", "--force", action="store_true", help="Overwrite (creates .bak.<ts>)")
    init_p.add_argument("--agents-only", action="store_true")
    init_p.add_argument("--kite-only", action="store_true")
    init_p.add_argument("--chat", action="store_true", help="Interactive init skill")
    init_p.set_defaults(func=cmd_init, cwd=os.getcwd())
