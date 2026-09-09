"""Headless task batch runner — JSONL or plain-text task files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kite.config import kite_home
from kite.tasks.headless import load_tasks_file, load_tasks_text, run_headless_batch


def _console():
    from kite.ui.style import make_console

    return make_console(stderr=True)


def _example_tasks() -> str:
    return (
        "# Kite headless tasks — one JSON object per line (or plain text lines)\n"
        '{"task": "Summarize this repo in 5 bullets", "label": "summary", "mode": "plan"}\n'
        '{"task": "Run pytest -q and report failures", "label": "tests", "approval": "auto"}\n'
    )


def cmd_tasks(args) -> int:
    action = getattr(args, "tasks_action", None)
    if not action:
        _console().print("[red]use: kite tasks run <file> | kite tasks init[/]")
        return 2
    console = _console()

    if action == "init":
        out = Path(args.path) if getattr(args, "path", None) else kite_home() / "tasks" / "example.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.is_file() and not getattr(args, "force", False):
            console.print(f"[red]exists: {out}[/]  use --force to overwrite")
            return 2
        out.write_text(_example_tasks(), encoding="utf-8")
        console.print(f"[green]wrote[/] {out}")
        console.print("[dim]run: kite tasks run " + str(out) + "[/]")
        return 0

    if action == "run":
        default_cwd = str(Path(getattr(args, "cwd", ".") or ".").resolve())
        try:
            if getattr(args, "stdin", False) or str(getattr(args, "file", "")) == "-":
                tasks = load_tasks_text(sys.stdin.read(), default_cwd=default_cwd)
            else:
                path = Path(args.file)
                if not path.is_file():
                    console.print(f"[red]not found: {path}[/]")
                    return 2
                tasks = load_tasks_file(path, default_cwd=default_cwd)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            return 2

        if getattr(args, "dry_run", False):
            for i, task in enumerate(tasks):
                label = task.label or task.task[:48]
                console.print(f"  {i + 1}. [{task.mode}/{task.approval}] {label}")
            return 0

        batch = run_headless_batch(
            tasks,
            continue_on_error=bool(getattr(args, "continue_on_error", False)),
            provider=getattr(args, "provider", None),
            model=getattr(args, "model", None),
            config_name=getattr(args, "config", None),
            stream_tools=not getattr(args, "no_stream", False),
            verbose=bool(getattr(args, "verbose", False)),
            no_context=bool(getattr(args, "no_context", False)),
            no_compact=bool(getattr(args, "no_compact", False)),
            no_guardrails=bool(getattr(args, "no_guardrails", False)),
        )
        if getattr(args, "json", False):
            print(json.dumps(batch.to_dict(), indent=2))
        else:
            for row in batch.results:
                mark = "ok" if row.ok else "fail"
                console.print(
                    f"[{'green' if row.ok else 'red'}]{mark}[/] "
                    f"{row.label}  exit={row.exit_status}  session={row.session_id or '—'}"
                )
            console.print(
                f"[dim]{batch.to_dict()['succeeded']}/{batch.to_dict()['total']} succeeded[/]"
            )
        return 0 if batch.ok else 1

    console.print("[red]use: kite tasks run <file.jsonl> | kite tasks init[/]")
    return 2


def add_tasks_parser(sub) -> None:
    tasks = sub.add_parser(
        "tasks",
        help="Run headless task batches (JSONL or plain text, no TTY)",
    )
    tasks_sub = tasks.add_subparsers(dest="tasks_action")

    init_p = tasks_sub.add_parser("init", help="Write ~/.kite/tasks/example.jsonl")
    init_p.add_argument("path", nargs="?", help="Output path (default ~/.kite/tasks/example.jsonl)")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing file")
    init_p.set_defaults(func=cmd_tasks, tasks_action="init")

    run_p = tasks_sub.add_parser("run", help="Run tasks from a file or stdin")
    run_p.add_argument(
        "file",
        nargs="?",
        default="-",
        help="Task file (.jsonl or one task per line). Use - for stdin",
    )
    run_p.add_argument("--stdin", action="store_true", help="Read tasks from stdin")
    run_p.add_argument("--cwd", default=".", help="Default workspace for tasks without cwd")
    run_p.add_argument("-p", "--provider", default=None)
    run_p.add_argument("-m", "--model", default=None)
    run_p.add_argument("--config", default=None, help="Runtime TOML overlay")
    run_p.add_argument("--continue-on-error", action="store_true", help="Keep batch after a failure")
    run_p.add_argument("--dry-run", action="store_true", help="List tasks without running")
    run_p.add_argument("--no-stream", action="store_true", help="Hide live bash/tool output lines")
    run_p.add_argument("-v", "--verbose", action="store_true", help="Stream model text deltas")
    run_p.add_argument("--no-context", action="store_true")
    run_p.add_argument("--no-compact", action="store_true")
    run_p.add_argument("--no-guardrails", action="store_true")
    run_p.add_argument("--json", action="store_true", help="Emit batch summary JSON on stdout")
    run_p.set_defaults(func=cmd_tasks, tasks_action="run")
