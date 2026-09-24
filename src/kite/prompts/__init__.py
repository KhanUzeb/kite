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


def _stable_parts(
    *,
    config: AgentRuntimeConfig,
    override_system: str | None = None,
    cwd: str | Path | None = None,
    project_context: ProjectContext | None = None,
) -> list[str]:
    """Cache-stable instructions: identical across turns for a given model."""
    prompts: PromptsConfig = config.prompts
    discovered_override, _ = discover_system_prompt_files(
        cwd if cwd is not None else (project_context.root if project_context else None)
    )
    base = (override_system or discovered_override or load_prompt_template(prompts.system)).strip()
    parts = [base]
    try:
        layers = load_prompt_template("memory_layers").strip()
        if layers:
            parts.append(layers)
    except (FileNotFoundError, OSError):
        pass
    return parts


def _setup_parts(
    *,
    config: AgentRuntimeConfig,
    project_context: ProjectContext | None = None,
    skills: list[Skill] | None = None,
    extra_sections: list[str] | None = None,
    append_system: str | None = None,
    memory: str | None = None,
    working_style: str | None = None,
    continuity: str | None = None,
    cwd: str | Path | None = None,
) -> list[str]:
    """Per-request setup: date, environment, repo state, skills, rules (§2 Move).

    Sent as a user-role message after the cache breakpoint so volatile values
    never invalidate the stable system prefix.
    """
    _, discovered_append = discover_system_prompt_files(
        cwd if cwd is not None else (project_context.root if project_context else None)
    )
    parts = [session_time_section()]
    append = (append_system if append_system is not None else discovered_append) or ""
    if append.strip():
        parts.append(append.strip())
    if project_context is not None:
        rendered = project_context.render_for_prompt(max_chars=config.context.max_context_chars)
        if rendered.strip():
            parts.append("# Active project context\n" + rendered.strip())
    if working_style and working_style.strip():
        parts.append(working_style.strip())
    if memory and memory.strip():
        parts.append(memory.strip())
    if continuity and continuity.strip():
        parts.append(continuity.strip())
    try:
        from kite.memory.working_notes import notes_block

        block = notes_block(cwd if cwd is not None else (project_context.root if project_context else None))
        if block:
            parts.append(block)
    except Exception:
        pass
    if config.skills.enabled and config.skills.auto_index_in_system_prompt and skills:
        parts.append(build_skill_index(skills))
    for section in extra_sections or []:
        if section and section.strip():
            parts.append(section.strip())
    return parts


def split_system_and_setup(
    *,
    config: AgentRuntimeConfig,
    project_context: ProjectContext | None = None,
    skills: list[Skill] | None = None,
    extra_sections: list[str] | None = None,
    override_system: str | None = None,
    append_system: str | None = None,
    memory: str | None = None,
    working_style: str | None = None,
    continuity: str | None = None,
    cwd: str | Path | None = None,
) -> tuple[str, str]:
    """Return (stable_system, setup) for cache-friendly request layout."""
    stable = "\n\n".join(p for p in _stable_parts(
        config=config, override_system=override_system, cwd=cwd, project_context=project_context,
    ) if p.strip()).strip() + "\n"
    setup = "\n\n".join(p for p in _setup_parts(
        config=config, project_context=project_context, skills=skills,
        extra_sections=extra_sections, append_system=append_system,
        memory=memory, working_style=working_style, continuity=continuity, cwd=cwd,
    ) if p.strip()).strip()
    if setup:
        setup += "\n"
    return stable, setup


def assemble_system_prompt(
    *,
    config: AgentRuntimeConfig,
    project_context: ProjectContext | None = None,
    skills: list[Skill] | None = None,
    extra_sections: list[str] | None = None,
    override_system: str | None = None,
    append_system: str | None = None,
    memory: str | None = None,
    working_style: str | None = None,
    continuity: str | None = None,
    cwd: str | Path | None = None,
) -> str:
    """Assemble the immutable-ish base prompt + optional append + live context.

    Override precedence (first wins): explicit ``override_system`` → discovered
    ``SYSTEM.md`` → bundled ``data/prompts/system.md``.

    Append (after base, before project context): explicit ``append_system`` then
    discovered ``APPEND_SYSTEM.md`` (explicit wins if both set — we only use one
    append source: explicit if provided, else discovered).

    Kept for backward compat (tests, bench, slots): new runs should prefer
    :func:`split_system_and_setup` so volatile setup rides after the cache
    breakpoint instead of invalidating the system prefix.
    """
    stable, setup = split_system_and_setup(
        config=config, project_context=project_context, skills=skills,
        extra_sections=extra_sections, override_system=override_system,
        append_system=append_system, memory=memory, working_style=working_style,
        continuity=continuity, cwd=cwd,
    )
    return "\n\n".join(p for p in (stable.strip(), setup.strip()) if p).strip() + "\n"


def assemble_instance_prompt(
    *,
    config: AgentRuntimeConfig,
    task: str,
    override_instance: str | None = None,
) -> str:
    template = override_instance or load_prompt_template(config.prompts.instance)
    return template.format(task=task)
