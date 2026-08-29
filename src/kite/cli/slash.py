"""Unified slash resolution: builtins, markdown commands, plugins, skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kite.commands.loader import (
    PromptCommand,
    expand_arguments,
    load_bundled_commands,
    load_commands_from_dir,
    project_commands_dir,
    user_commands_dir,
)
from kite.plugins.loader import Plugin, load_plugins
from kite.skills.loader import Skill, expand_skill_slash, format_skill_invocation, load_skills
from kite.ui.commands import SlashResult, parse_slash


@dataclass(frozen=True)
class SlashSpec:
    name: str
    kind: str  # control | prompt
    source: str  # builtin | bundled | user | project | plugin | skill
    description: str
    body: str = ""
    path: Path | None = None
    plugin: str = ""
    hint: str = ""


@dataclass
class CommandIndex:
    specs: dict[str, SlashSpec] = field(default_factory=dict)
    skills: list[Skill] = field(default_factory=list)
    plugins: list[Plugin] = field(default_factory=list)
    commands: list[PromptCommand] = field(default_factory=list)

    def get(self, name: str) -> SlashSpec | None:
        return self.specs.get(name.strip().lower().lstrip("/"))

    def prompt_specs(self) -> list[SlashSpec]:
        return [s for s in self.specs.values() if s.kind == "prompt"]

    @classmethod
    def load(cls, cwd: str | Path = ".", extra_skill_dirs: list[str] | None = None) -> CommandIndex:
        cwd_path = Path(cwd).expanduser().resolve()
        extra = list(extra_skill_dirs or [])
        plugins = load_plugins(cwd_path)
        skills = load_skills(cwd_path, extra_dirs=extra)

        specs: dict[str, SlashSpec] = {}
        overlay: list[PromptCommand] = []

        def put(spec: SlashSpec, *, alias: str | None = None) -> None:
            key = (alias or spec.name).lower()
            specs[key] = spec

        def add_commands(items: list[PromptCommand] | tuple[PromptCommand, ...]) -> None:
            for cmd in items:
                overlay.append(cmd)
                spec = SlashSpec(
                    name=cmd.name,
                    kind="prompt",
                    source=cmd.source,
                    description=cmd.description or (cmd.body.splitlines()[0][:80] if cmd.body else ""),
                    body=cmd.body,
                    path=cmd.path,
                    plugin=cmd.plugin,
                    hint=cmd.argument_hint,
                )
                put(spec)
                if cmd.plugin:
                    put(spec, alias=f"{cmd.plugin}:{cmd.name}")

        # Later wins: bundled → user → plugins → project. Skills fill unused names.
        add_commands(load_bundled_commands())
        add_commands(load_commands_from_dir(user_commands_dir(), source="user"))
        for plugin in plugins:
            add_commands(plugin.commands)
        add_commands(load_commands_from_dir(project_commands_dir(cwd_path), source="project"))

        for skill in skills:
            key = skill.name.lower()
            skill_spec = SlashSpec(
                name=key,
                kind="prompt",
                source="skill",
                description=skill.description or "",
                body=skill.content,
                path=skill.path,
            )
            if key not in specs:
                put(skill_spec)
            put(skill_spec, alias=f"skill:{key}")

        return cls(specs=specs, skills=skills, plugins=plugins, commands=overlay)

    def expand(self, name: str, arg: str = "") -> str | None:
        spec = self.get(name)
        if spec is None or spec.kind != "prompt":
            return None
        if spec.source == "skill":
            skill = next((s for s in self.skills if s.name.lower() == spec.name), None)
            if skill is None:
                return None
            return format_skill_invocation(skill, arg or None)
        return expand_arguments(spec.body, arg)


def resolve_slash(raw: str, index: CommandIndex) -> SlashResult:
    parsed = parse_slash(raw)
    if parsed.kind == "not_slash":
        return parsed

    if parsed.kind == "handled":
        if parsed.command == "skill" and parsed.arg:
            name, _, extra = parsed.arg.partition(" ")
            prompt = index.expand(f"skill:{name}", extra.strip()) or index.expand(name, extra.strip())
            if prompt is None:
                # /skill name — try skill loader aliases
                try:
                    expanded = expand_skill_slash(f"/skill:{parsed.arg}", index.skills)
                except KeyError:
                    expanded = None
                if expanded:
                    return SlashResult("prompt", command=name.lower(), arg=extra.strip(), prompt=expanded, source="skill")
                return SlashResult(
                    "unknown",
                    command="skill",
                    arg=parsed.arg,
                    message=f"unknown skill '{name}'  — /skills",
                )
            source = (index.get(f"skill:{name}") or index.get(name) or SlashSpec(name, "prompt", "skill", "")).source
            return SlashResult("prompt", command=name.lower(), arg=extra.strip(), prompt=prompt, source=source)
        return parsed

    # unknown builtin name — commands, plugins, skills, /skill:foo
    name = parsed.command
    arg = parsed.arg
    if name.startswith("skill:"):
        rest = name.split(":", 1)[1]
        name, arg = rest, parsed.arg
        prompt = index.expand(f"skill:{name}", arg)
    else:
        prompt = index.expand(name, arg)
    if prompt is not None:
        spec = index.get(parsed.command) or index.get(name)
        source = spec.source if spec else "command"
        return SlashResult("prompt", command=name, arg=arg, prompt=prompt, source=source)
    try:
        expanded = expand_skill_slash(raw.strip(), index.skills)
    except KeyError as e:
        return SlashResult("unknown", command=name, arg=arg, message=str(e) + "  — /skills")
    if expanded is not None:
        return SlashResult("prompt", command=name, arg=arg, prompt=expanded, source="skill")
    return parsed


def expand_prompt_slash(
    text: str,
    cwd: str | Path = ".",
    extra_skill_dirs: list[str] | None = None,
) -> str:
    """Expand a prompt-kind slash (command/skill) for one-shot `kite run`. Control slashes left as-is."""
    stripped = text.strip()
    if not stripped.startswith("/") or stripped.startswith("//"):
        return text
    index = CommandIndex.load(cwd, extra_skill_dirs=extra_skill_dirs)
    hit = resolve_slash(stripped, index)
    if hit.kind == "prompt" and hit.prompt:
        return hit.prompt
    if hit.kind == "unknown":
        raise RuntimeError(hit.message)
    return text


def help_text(index: CommandIndex) -> str:
    from kite.ui.commands import HELP

    lines = [HELP.strip(), "", "skills & commands"]
    seen: set[str] = set()
    rows = sorted(index.prompt_specs(), key=lambda s: (s.source, s.name))
    for spec in rows:
        if spec.name in seen:
            continue
        seen.add(spec.name)
        tag = spec.plugin or spec.source
        hint = f" {spec.hint}" if spec.hint else ""
        desc = (spec.description or "").strip()
        if len(desc) > 56:
            desc = desc[:55] + "…"
        lines.append(f"/{spec.name:<16} ({tag}){hint}  {desc}".rstrip())
        if len(seen) >= 40:
            lines.append("…  /skills  /commands  /plugins")
            break
    if not seen:
        lines.append("(none yet — /commands new name  or  /plugins init name)")
    return "\n".join(lines)
