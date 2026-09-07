"""Strip sensitive keys before spawning child processes."""

from __future__ import annotations

import os
import re

_DROP_ENV_EXACT = frozenset(
    {
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SESSION_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "GITLAB_PRIVATE_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HF_TOKEN",
        "KITE_MAINTAINER_KEY",
        "NVIDIA_NIM_API_KEY",
        "NGC_API_KEY",
        "OPENROUTER_API_KEY",
        "XAI_API_KEY",
        "CHATGPT_API_KEY",
    }
)

_DROP_ENV_PREFIXES = (
    "AZURE_",
    "GITLAB_",
    "OPENROUTER_",
    "GITHUB_",
    "AWS_",
)

_SENSITIVE_SUFFIX = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)$")


def is_sensitive_env_key(name: str) -> bool:
    upper = name.upper()
    if upper in _DROP_ENV_EXACT:
        return True
    if any(upper.startswith(p) for p in _DROP_ENV_PREFIXES):
        return True
    return bool(_SENSITIVE_SUFFIX.search(upper))


def filtered_child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of os.environ with credential-like keys removed."""
    env = {k: v for k, v in os.environ.items() if not is_sensitive_env_key(k)}
    if extra:
        env.update(extra)
    return env
