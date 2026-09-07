"""Resolve API keys from catalog env names plus a few well-known aliases."""

from __future__ import annotations

import os

from kite.providers.catalog import ProviderSpec

# Extra env vars checked after spec.api_key_env (first hit wins).
_FALLBACKS: dict[str, tuple[str, ...]] = {
    "nvidia": ("NVIDIA_NIM_API_KEY", "NGC_API_KEY"),
    "opencode-zen": ("OPENCODE_ZEN_API_KEY",),
    "opencode-go": ("OPENCODE_GO_API_KEY",),
}


def api_key_env_names(spec: ProviderSpec) -> tuple[str, ...]:
    names: list[str] = []
    if spec.api_key_env:
        names.append(spec.api_key_env)
    for extra in _FALLBACKS.get(spec.name, ()):
        if extra not in names:
            names.append(extra)
    return tuple(names)


def api_key_for(spec: ProviderSpec) -> str | None:
    for name in api_key_env_names(spec):
        val = os.getenv(name)
        if val and val.strip():
            return val.strip()
    return None
