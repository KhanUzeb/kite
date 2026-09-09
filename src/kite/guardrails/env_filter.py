"""Strip sensitive keys before spawning child processes."""

from __future__ import annotations

import logging
import os
import re

_log = logging.getLogger(__name__)

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
        "CONTEXT7_API_KEY",
        "TAVILY_API_KEY",
        "EXA_API_KEY",
        "FIRECRAWL_API_KEY",
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


class SensitiveEnvInjectionError(ValueError):
    """Raised when ``extra`` attempts to inject credential-like environment keys."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = keys
        super().__init__(f"refused sensitive environment keys: {', '.join(keys)}")


def filtered_child_env(extra: dict[str, str] | None = None, *, strict: bool = False) -> dict[str, str]:
    """Return a copy of os.environ with credential-like keys removed.

    Keys in ``extra`` that look sensitive are refused (never re-injected after filtering).
    """
    env = {k: v for k, v in os.environ.items() if not is_sensitive_env_key(k)}
    if not extra:
        return env
    rejected: list[str] = []
    for key, value in extra.items():
        if is_sensitive_env_key(key):
            rejected.append(key)
        else:
            env[key] = value
    if rejected:
        names = ", ".join(sorted(rejected))
        _log.warning("refused to inject sensitive environment keys: %s", names)
        if strict:
            raise SensitiveEnvInjectionError(tuple(sorted(rejected)))
    return env
