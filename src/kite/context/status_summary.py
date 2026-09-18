"""Human-readable project + memory lines for /status and `kite context`."""

from __future__ import annotations

from pathlib import Path

from kite.context.ci_hints import canonical_test_command
from kite.context.discovery import find_project_root
from kite.context.project_init import detect_ecosystem, needs_agents_bootstrap
from kite.memory.user_context import profile_path, user_path
from kite.memory.working_style import working_path


def _exists_line(label: str, path: Path) -> str:
    mark = "yes" if path.is_file() else "no"
    return f"{label} {path} ({mark})"


def project_context_summary(cwd: str | Path) -> list[str]:
    root = find_project_root(Path(cwd).expanduser().resolve())
    lines = [f"project_root  {root}"]
    if needs_agents_bootstrap(root):
        lines.append("agents        no root AGENTS.md — kite init or /init")
    else:
        lines.append("agents        root AGENTS.md present")
    ci = canonical_test_command(root)
    eco = detect_ecosystem(root)
    verify = ci or eco.test
    src = "CI" if ci else "manifest"
    lines.append(f"verify ({src})  {verify}")
    return lines


def memory_context_summary() -> list[str]:
    return [
        _exists_line("USER", user_path()),
        _exists_line("PROFILE", profile_path()),
        _exists_line("WORKING", working_path()),
    ]
