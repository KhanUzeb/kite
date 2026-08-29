"""Load and merge agent runtime configs (packaged + user + CLI overrides)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path
from typing import Any

from kite.config.user import kite_home


@dataclass
class GuardrailConfig:
    enabled: bool = True
    sandbox_to_cwd: bool = True
    allow_paths_outside_cwd: bool = False
    deny_bash_patterns: list[str] = field(default_factory=list)
    block_secret_writes: bool = True
    max_bash_output_chars: int = 100_000
    max_read_chars: int = 200_000


@dataclass
class SkillsConfig:
    enabled: bool = True
    auto_index_in_system_prompt: bool = True
    dirs: list[str] = field(default_factory=list)


@dataclass
class ContextConfig:
    include_git_status: bool = True
    include_tree_snippet: bool = True
    tree_max_entries: int = 80
    max_context_chars: int = 24_000


@dataclass
class ToolsConfig:
    enabled: list[str] = field(
        default_factory=lambda: [
            "read",
            "write",
            "edit",
            "bash",
            "grep",
            "glob",
            "ls",
            "skill",
            "todo_write",
            "todo_read",
            "task",
            "webfetch",
            "websearch",
            "webcrawl",
            "memory",
        ]
    )
    bash_timeout_seconds: int = 30


@dataclass
class PromptsConfig:
    system: str = "system"
    instance: str = "instance"


@dataclass
class AgentRuntimeConfig:
    name: str = "kite-default"
    step_limit: int = 40
    cost_limit: float = 5.0
    wall_time_limit_seconds: int = 0
    max_consecutive_format_errors: int = 3
    auto_compact: bool = True
    compaction_reserve_tokens: int = 16_384
    compaction_keep_recent_tokens: int = 20_000
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    context: ContextConfig = field(default_factory=ContextConfig)

    def with_overrides(self, **kwargs: Any) -> AgentRuntimeConfig:
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})


def _deep_get(data: dict, *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _from_dict(data: dict[str, Any]) -> AgentRuntimeConfig:
    agent = data.get("agent") or {}
    prompts = data.get("prompts") or {}
    tools = data.get("tools") or {}
    guard = data.get("guardrails") or {}
    skills = data.get("skills") or {}
    context = data.get("context") or {}
    return AgentRuntimeConfig(
        name=str(agent.get("name", "kite-default")),
        step_limit=int(agent.get("step_limit", 40)),
        cost_limit=float(agent.get("cost_limit", 5.0)),
        wall_time_limit_seconds=int(agent.get("wall_time_limit_seconds", 0)),
        max_consecutive_format_errors=int(agent.get("max_consecutive_format_errors", 3)),
        auto_compact=bool(agent.get("auto_compact", True)),
        compaction_reserve_tokens=int(agent.get("compaction_reserve_tokens", 16_384)),
        compaction_keep_recent_tokens=int(agent.get("compaction_keep_recent_tokens", 20_000)),
        prompts=PromptsConfig(
            system=str(prompts.get("system", "system")),
            instance=str(prompts.get("instance", "instance")),
        ),
        tools=ToolsConfig(
            enabled=list(
                tools.get("enabled")
                or [
                    "read",
                    "write",
                    "edit",
                    "bash",
                    "grep",
                    "glob",
                    "ls",
                    "skill",
                    "todo_write",
                    "todo_read",
                    "task",
                    "webfetch",
                    "memory",
                ]
            ),
            bash_timeout_seconds=int(tools.get("bash_timeout_seconds", 30)),
        ),
        guardrails=GuardrailConfig(
            enabled=bool(guard.get("enabled", True)),
            sandbox_to_cwd=bool(guard.get("sandbox_to_cwd", True)),
            allow_paths_outside_cwd=bool(guard.get("allow_paths_outside_cwd", False)),
            deny_bash_patterns=list(guard.get("deny_bash_patterns") or []),
            block_secret_writes=bool(guard.get("block_secret_writes", True)),
            max_bash_output_chars=int(guard.get("max_bash_output_chars", 100_000)),
            max_read_chars=int(guard.get("max_read_chars", 200_000)),
        ),
        skills=SkillsConfig(
            enabled=bool(skills.get("enabled", True)),
            auto_index_in_system_prompt=bool(skills.get("auto_index_in_system_prompt", True)),
            dirs=list(skills.get("dirs") or []),
        ),
        context=ContextConfig(
            include_git_status=bool(context.get("include_git_status", True)),
            include_tree_snippet=bool(context.get("include_tree_snippet", True)),
            tree_max_entries=int(context.get("tree_max_entries", 80)),
            max_context_chars=int(context.get("max_context_chars", 24_000)),
        ),
    )


def _merge_dict(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _read_packaged(name: str) -> dict[str, Any]:
    pkg = resources.files("kite").joinpath(f"data/configs/{name}.toml")
    return tomllib.loads(pkg.read_bytes().decode("utf-8"))


def load_runtime_config(name_or_path: str | Path | None = None) -> AgentRuntimeConfig:
    """Load packaged default, merge user overlay, then optional named/path config."""
    data = _read_packaged("default")

    user_default = kite_home() / "configs" / "default.toml"
    if user_default.is_file():
        data = _merge_dict(data, _read_toml(user_default))

    if name_or_path:
        path = Path(name_or_path)
        if path.is_file():
            data = _merge_dict(data, _read_toml(path))
        else:
            # named config: packaged or ~/.kite/configs/<name>.toml
            user = kite_home() / "configs" / f"{name_or_path}.toml"
            if user.is_file():
                data = _merge_dict(data, _read_toml(user))
            else:
                try:
                    data = _merge_dict(data, _read_packaged(str(name_or_path)))
                except (FileNotFoundError, OSError):
                    pass

    return _from_dict(data)
