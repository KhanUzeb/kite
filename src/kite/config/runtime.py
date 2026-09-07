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
    execution_mode: str = "host"  # restricted | host
    trusted_paths: list[str] = field(default_factory=list)  # relative subtrees with elevated bash trust
    deny_bash_patterns: list[str] = field(default_factory=list)
    block_secret_writes: bool = True
    max_bash_output_chars: int = 32_768
    max_read_chars: int = 200_000

    def host_access(self) -> bool:
        """True when file/shell tools may reach paths outside the session cwd."""
        if self.execution_mode == "host":
            return True
        return self.allow_paths_outside_cwd


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
    max_context_chars: int = 12_000


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
            "set_cwd",
            "skill",
            "todo_write",
            "todo_read",
            "task",
            "webfetch",
            "websearch",
            "webcrawl",
            "subagent",
            "memory",
        ]
    )
    bash_timeout_seconds: int = 120
    progress_interval_seconds: float = 5.0


@dataclass
class PromptsConfig:
    system: str = "system"
    instance: str = "instance"


@dataclass
class MemoryConfig:
    inject: str = "opt_in"  # opt_in | always


@dataclass
class AgentRuntimeConfig:
    name: str = "kite-default"
    step_limit: int = 40
    cost_limit: float = 5.0
    wall_time_limit_seconds: int = 0
    max_consecutive_format_errors: int = 3
    auto_compact: bool = True
    compaction_ratio: float = 0.75
    compaction_llm_ratio: float = 0.92
    observation_max_chars: int = 5_000
    compaction_reserve_tokens: int = 12_288
    compaction_keep_recent_tokens: int = 12_000
    interactive_step_limit: int = 80
    interactive_cost_limit: float = 10.0
    max_budget_continues: int = 2
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    github_tools: bool = False
    context7_enabled: bool = True
    role: str = "auto"
    prompt_cache_enabled: bool = True
    orchestrator_max_workers: int = 3
    orchestrator_step_limit: int = 10
    orchestrator_cost_limit: float = 1.0
    orchestrator_timeout_seconds: int = 300
    ui_theme: str = "auto"
    ui_font: str = "unicode"
    model_timeout_seconds: int = 180
    verify_before_submit: bool = True
    loop_hard_threshold: int = 5
    provider_max_retries: int = 4
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    auto_venv: bool = True

    def with_overrides(self, **kwargs: Any) -> AgentRuntimeConfig:
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})


def _from_dict(data: dict[str, Any]) -> AgentRuntimeConfig:
    agent = data.get("agent") or {}
    prompts = data.get("prompts") or {}
    tools = data.get("tools") or {}
    guard = data.get("guardrails") or {}
    skills = data.get("skills") or {}
    context = data.get("context") or {}
    cache = data.get("cache") or {}
    orch = data.get("orchestrator") or {}
    ui = data.get("ui") or {}
    memory = data.get("memory") or {}
    env_cfg = data.get("environment") or {}
    return AgentRuntimeConfig(
        name=str(agent.get("name", "kite-default")),
        step_limit=int(agent.get("step_limit", 40)),
        cost_limit=float(agent.get("cost_limit", 5.0)),
        wall_time_limit_seconds=int(agent.get("wall_time_limit_seconds", 0)),
        model_timeout_seconds=int(agent.get("model_timeout_seconds", 180)),
        verify_before_submit=bool(agent.get("verify_before_submit", True)),
        loop_hard_threshold=int(agent.get("loop_hard_threshold", 5)),
        provider_max_retries=int(agent.get("provider_max_retries", 4)),
        max_consecutive_format_errors=int(agent.get("max_consecutive_format_errors", 3)),
        auto_compact=bool(agent.get("auto_compact", True)),
        compaction_ratio=float(agent.get("compaction_ratio", 0.75)),
        compaction_llm_ratio=float(agent.get("compaction_llm_ratio", 0.92)),
        observation_max_chars=int(agent.get("observation_max_chars", 5_000)),
        compaction_reserve_tokens=int(agent.get("compaction_reserve_tokens", 12_288)),
        compaction_keep_recent_tokens=int(agent.get("compaction_keep_recent_tokens", 12_000)),
        interactive_step_limit=int(agent.get("interactive_step_limit", 80)),
        interactive_cost_limit=float(agent.get("interactive_cost_limit", 10.0)),
        max_budget_continues=int(agent.get("max_budget_continues", 2)),
        prompts=PromptsConfig(
            system=str(prompts.get("system", "system")),
            instance=str(prompts.get("instance", "instance")),
        ),
        tools=ToolsConfig(
            enabled=list(tools["enabled"]) if "enabled" in tools else ToolsConfig().enabled,
            bash_timeout_seconds=int(tools.get("bash_timeout_seconds", 120)),
            progress_interval_seconds=float(tools.get("progress_interval_seconds", 5.0)),
        ),
        guardrails=GuardrailConfig(
            enabled=bool(guard.get("enabled", True)),
            sandbox_to_cwd=bool(guard.get("sandbox_to_cwd", True)),
            allow_paths_outside_cwd=bool(guard.get("allow_paths_outside_cwd", False)),
            execution_mode=str(guard.get("execution_mode", "host")),
            trusted_paths=list(guard.get("trusted_paths") or []),
            deny_bash_patterns=list(guard.get("deny_bash_patterns") or []),
            block_secret_writes=bool(guard.get("block_secret_writes", True)),
            max_bash_output_chars=int(guard.get("max_bash_output_chars", 32_768)),
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
            max_context_chars=int(context.get("max_context_chars", 12_000)),
        ),
        github_tools=bool((data.get("github") or {}).get("enabled", False)),
        context7_enabled=bool((data.get("context7") or {}).get("enabled", True)),
        role=str(agent.get("role", "auto")),
        prompt_cache_enabled=bool(cache.get("enabled", True)),
        orchestrator_max_workers=int(orch.get("max_workers", 3)),
        orchestrator_step_limit=int(orch.get("step_limit", 10)),
        orchestrator_cost_limit=float(orch.get("cost_limit", 1.0)),
        orchestrator_timeout_seconds=int(orch.get("timeout_seconds", 300)),
        ui_theme=str(ui.get("theme") or "auto"),
        ui_font=str(ui.get("font") or "unicode"),
        memory=MemoryConfig(inject=str(memory.get("inject", "opt_in"))),
        auto_venv=bool(env_cfg.get("auto_venv", True)),
    )


def _merge_dict(base: dict, overlay: dict) -> dict:
    out = dict(base)
    merge_lists = {"trusted_paths", "deny_bash_patterns", "dirs"}
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_dict(out[k], v)
        elif isinstance(v, list) and isinstance(out.get(k), list) and k in merge_lists:
            seen = set(out[k])
            out[k] = list(out[k]) + [item for item in v if item not in seen]
        else:
            out[k] = v
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _read_packaged(name: str) -> dict[str, Any]:
    pkg = resources.files("kite").joinpath(f"data/configs/{name}.toml")
    return tomllib.loads(pkg.read_bytes().decode("utf-8"))


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        return 0.0


_RUNTIME_CACHE: dict[tuple[str, str, float, float], AgentRuntimeConfig] = {}


def load_runtime_config(name_or_path: str | Path | None = None) -> AgentRuntimeConfig:
    """Load packaged default, merge user overlay, then optional named/path config."""
    user_default = kite_home() / "configs" / "default.toml"
    extra = Path(name_or_path) if name_or_path else None
    key = (
        str(name_or_path or ""),
        str(kite_home()),
        _file_mtime(user_default),
        _file_mtime(extra) if extra is not None else 0.0,
    )
    hit = _RUNTIME_CACHE.get(key)
    if hit is not None:
        return hit
    data = _read_packaged("default")

    if user_default.is_file():
        data = _merge_dict(data, _read_toml(user_default))

    if name_or_path:
        path = Path(name_or_path)
        if path.is_file():
            data = _merge_dict(data, _read_toml(path))
        else:
            user = kite_home() / "configs" / f"{name_or_path}.toml"
            if user.is_file():
                data = _merge_dict(data, _read_toml(user))
            else:
                try:
                    data = _merge_dict(data, _read_packaged(str(name_or_path)))
                except (FileNotFoundError, OSError) as exc:
                    import warnings

                    warnings.warn(f"unknown runtime config {name_or_path!r}: {exc}", stacklevel=2)

    cfg = _from_dict(data)
    _RUNTIME_CACHE[key] = cfg
    return cfg
