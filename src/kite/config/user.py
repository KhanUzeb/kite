"""Paths and user preferences (~/.kite/)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomli_w
except ImportError:  # pragma: no cover
    tomli_w = None  # type: ignore


_ensured: set[str] = set()


def kite_home() -> Path:
    override = os.getenv("KITE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".kite"


def ensure_home() -> Path:
    home = kite_home()
    key = str(home)
    if key in _ensured:
        return home
    for name in ("sessions", "trajectories", "skills", "commands", "plugins", "memory", "configs", "extensions", "attachments", "checkpoints", "oauth"):
        (home / name).mkdir(parents=True, exist_ok=True)
    _ensured.add(key)
    return home


@dataclass
class UserConfig:
    default_provider: str = "openai"
    default_model: str | None = None
    step_limit: int = 40
    cost_limit: float = 5.0
    context_window: int | None = None
    compaction_reserve_tokens: int = 16_384
    compaction_keep_recent_tokens: int = 20_000
    auto_compact: bool = True
    include_git_status: bool = True
    include_tree_snippet: bool = True
    tree_max_entries: int = 80
    api_bases: dict[str, str] = field(default_factory=dict)
    api_styles: dict[str, str] = field(default_factory=dict)  # provider -> chat|messages|responses
    # provider -> model override default
    provider_defaults: dict[str, str] = field(default_factory=dict)
    compaction_provider: str = "openrouter"
    compaction_model: str | None = None  # None = first live free-tier model
    compaction_use_llm: bool = True
    reasoning: str = "auto"
    theme: str = ""
    font: str = ""

    @property
    def path(self) -> Path:
        """Resolved path to ~/.kite/config.toml (file may not exist yet)."""
        return kite_home() / "config.toml"

    @classmethod
    def load(cls) -> UserConfig:
        global _USER_CONFIG_CACHE
        ensure_home()
        path = kite_home() / "config.toml"
        mtime = path.stat().st_mtime if path.is_file() else 0.0
        if _USER_CONFIG_CACHE is not None and _USER_CONFIG_CACHE[0] == mtime:
            return _USER_CONFIG_CACHE[1]
        if not path.is_file():
            cfg = cls()
        else:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            cfg = cls(
                default_provider=str(data.get("default_provider", "openai")),
                default_model=data.get("default_model"),
                step_limit=int(data.get("step_limit", 40)),
                cost_limit=float(data.get("cost_limit", 5.0)),
                context_window=data.get("context_window"),
                compaction_reserve_tokens=int(data.get("compaction_reserve_tokens", 16_384)),
                compaction_keep_recent_tokens=int(data.get("compaction_keep_recent_tokens", 20_000)),
                auto_compact=bool(data.get("auto_compact", True)),
                include_git_status=bool(data.get("include_git_status", True)),
                include_tree_snippet=bool(data.get("include_tree_snippet", True)),
                tree_max_entries=int(data.get("tree_max_entries", 80)),
                api_bases=dict(data.get("api_bases") or {}),
                api_styles=dict(data.get("api_styles") or {}),
                provider_defaults=dict(data.get("provider_defaults") or {}),
                compaction_provider=str(data.get("compaction_provider") or "openrouter"),
                compaction_model=data.get("compaction_model") or None,
                compaction_use_llm=bool(data.get("compaction_use_llm", True)),
                reasoning=str(data.get("reasoning") or "auto"),
                theme=str(data.get("theme") or ""),
                font=str(data.get("font") or ""),
            )
        _USER_CONFIG_CACHE = (mtime, cfg)
        return cfg

    def save(self) -> Path:
        ensure_home()
        path = kite_home() / "config.toml"
        payload = {
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "step_limit": self.step_limit,
            "cost_limit": self.cost_limit,
            "context_window": self.context_window,
            "compaction_reserve_tokens": self.compaction_reserve_tokens,
            "compaction_keep_recent_tokens": self.compaction_keep_recent_tokens,
            "auto_compact": self.auto_compact,
            "include_git_status": self.include_git_status,
            "include_tree_snippet": self.include_tree_snippet,
            "tree_max_entries": self.tree_max_entries,
            "api_bases": self.api_bases,
            "api_styles": self.api_styles,
            "provider_defaults": self.provider_defaults,
            "compaction_provider": self.compaction_provider,
            "compaction_model": self.compaction_model,
            "compaction_use_llm": self.compaction_use_llm,
            "reasoning": self.reasoning,
            "theme": self.theme,
            "font": self.font,
        }
        # tomli_w cannot serialize None; omit null optional fields
        payload = {k: v for k, v in payload.items() if v is not None}
        if tomli_w is None:
            # Minimal TOML writer fallback
            lines = []
            for k, v in payload.items():
                if isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str) or v is None:
                    if v is None:
                        continue
                    lines.append(f'{k} = "{v}"')
                elif isinstance(v, (int, float)):
                    lines.append(f"{k} = {v}")
                elif isinstance(v, dict):
                    lines.append(f"\n[{k}]")
                    for dk, dv in v.items():
                        lines.append(f'{dk} = "{dv}"')
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        _invalidate_user_config_cache()
        return path


_USER_CONFIG_CACHE: tuple[float, UserConfig] | None = None


def _invalidate_user_config_cache() -> None:
    global _USER_CONFIG_CACHE
    _USER_CONFIG_CACHE = None
