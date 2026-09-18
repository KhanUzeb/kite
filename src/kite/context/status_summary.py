"""Short status lines for /status and `kite context`."""

from __future__ import annotations

from pathlib import Path

from kite.context.discovery import find_project_root
from kite.context.project_init import needs_agents_bootstrap
from kite.context.verify_hint import resolve_verification_command
from kite.memory.user_context import profile_path, user_path
from kite.memory.working_style import working_path


def project_context_summary(cwd: str | Path) -> list[str]:
    root = find_project_root(Path(cwd).expanduser().resolve())
    cmd, src = resolve_verification_command(root)
    agents = "missing — kite init" if needs_agents_bootstrap(root) else "ok"
    return [
        f"project_root  {root}",
        f"agents        {agents}",
        f"verify ({src or '—'})  {cmd or '—'}",
    ]


def context_preview_body(ctx, *, max_chars: int = 4_000) -> str:
    return ctx.render_for_prompt(max_chars=max_chars)


def memory_context_summary() -> list[str]:
    def line(label: str, path: Path) -> str:
        return f"{label}  {path} ({'yes' if path.is_file() else 'no'})"

    return [line("USER", user_path()), line("PROFILE", profile_path()), line("WORKING", working_path())]
