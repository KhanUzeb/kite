"""User prefs (~/.kite) and merged agent runtime TOML.

Heavy readiness helpers load on first use so `from kite.config import UserConfig`
does not pull credentials / BYOS auth on CLI cold start.
"""

from kite.config.runtime import (
    AgentRuntimeConfig,
    ContextConfig,
    GuardrailConfig,
    PromptsConfig,
    SkillsConfig,
    ToolsConfig,
    load_runtime_config,
)
from kite.config.user import UserConfig, ensure_home, kite_home

__all__ = [
    "AgentRuntimeConfig",
    "ContextConfig",
    "GuardrailConfig",
    "PromptsConfig",
    "SkillsConfig",
    "ToolsConfig",
    "UserConfig",
    "SetupStatus",
    "assess_setup_status",
    "ensure_home",
    "is_fresh_install",
    "kite_home",
    "load_runtime_config",
    "needs_setup",
]


def __getattr__(name: str):
    if name in {"SetupStatus", "assess_setup_status", "is_fresh_install", "needs_setup"}:
        from kite.config import readiness as _readiness

        return getattr(_readiness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
