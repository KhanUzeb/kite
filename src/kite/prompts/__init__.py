"""System / instance prompt assembly."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path

from kite.config import AgentRuntimeConfig, PromptsConfig
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


def assemble_system_prompt(
    *,
    config: AgentRuntimeConfig,
    project_context: ProjectContext | None = None,
    skills: list[Skill] | None = None,
    extra_sections: list[str] | None = None,
    override_system: str | None = None,
    memory: str | None = None,
) -> str:
    prompts: PromptsConfig = config.prompts
    base = override_system or load_prompt_template(prompts.system)
    parts = [base.strip()]

    if project_context is not None:
        rendered = project_context.render_for_prompt(max_chars=config.context.max_context_chars)
        if rendered.strip():
            parts.append("# Active project context\n" + rendered.strip())

    if memory and memory.strip():
        parts.append(memory.strip())

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
