"""System / instance prompt assembly."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

from kite.config import AgentRuntimeConfig, PromptsConfig
from kite.context.clock import session_time_section
from kite.context.discovery import ProjectContext
from kite.skills.loader import Skill, build_skill_index


@lru_cache(maxsize=64)
def _load_packaged_prompt(stem: str) -> str:
    pkg = resources.files("kite").joinpath(f"data/prompts/{stem}.md")
    return pkg.read_bytes().decode("utf-8")


def load_prompt_template(name: str) -> str:
    """Load `data/prompts/<name>.md`, or a filesystem path if it exists."""
    path = Path(name)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return _load_packaged_prompt(name)


def _read_prompt_file(*candidates: Path) -> str | None:
    for path in candidates:
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except OSError:
            continue
    return None


def discover_system_prompt_files(cwd: str | Path | None = None) -> tuple[str | None, str | None]:
    """Pi/Prime-style SYSTEM.md (replace) and APPEND_SYSTEM.md (append).

    Precedence for each file: project `.kite/` then `~/.kite/`.
    """
    from kite.config.user import kite_home

    root = Path(cwd or ".").expanduser().resolve()
    home = kite_home()
    override = _read_prompt_file(root / ".kite" / "SYSTEM.md", home / "SYSTEM.md")
    append = _read_prompt_file(root / ".kite" / "APPEND_SYSTEM.md", home / "APPEND_SYSTEM.md")
    return override, append


def assemble_system_prompt(
    *,
    config: AgentRuntimeConfig,
    project_context: ProjectContext | None = None,
    skills: list[Skill] | None = None,
    extra_sections: list[str] | None = None,
    override_system: str | None = None,
    append_system: str | None = None,
    memory: str | None = None,
    continuity: str | None = None,
    cwd: str | Path | None = None,
) -> str:
    """Assemble the immutable-ish base prompt + optional append + live context.

    Override precedence (first wins): explicit ``override_system`` → discovered
    ``SYSTEM.md`` → bundled ``data/prompts/system.md``.

    Append (after base, before project context): explicit ``append_system`` then
    discovered ``APPEND_SYSTEM.md`` (explicit wins if both set — we only use one
    append source: explicit if provided, else discovered).
    """
    prompts: PromptsConfig = config.prompts
    discovered_override, discovered_append = discover_system_prompt_files(
        cwd if cwd is not None else (project_context.root if project_context else None)
    )
    base = (override_system or discovered_override or load_prompt_template(prompts.system)).strip()
    parts = [session_time_section(), base]

    append = (append_system if append_system is not None else discovered_append) or ""
    if append.strip():
        parts.append(append.strip())

    if project_context is not None:
        rendered = project_context.render_for_prompt(max_chars=config.context.max_context_chars)
        if rendered.strip():
            parts.append("# Active project context\n" + rendered.strip())

    if memory and memory.strip():
        parts.append(memory.strip())

    if continuity and continuity.strip():
        parts.append(continuity.strip())

    if config.skills.enabled and config.skills.auto_index_in_system_prompt and skills:
        parts.append(build_skill_index(skills))

    for section in extra_sections or []:
        if section and section.strip():
            parts.append(section.strip())

    return "\n\n".join(parts).strip() + "\n"


def assemble_instance_prompt(
    *,
    config: AgentRuntimeConfig,
    task: str,
    override_instance: str | None = None,
) -> str:
    template = override_instance or load_prompt_template(config.prompts.instance)
    return template.format(task=task)
