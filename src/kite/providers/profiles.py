"""Concrete provider wire profiles — one source for backend + frontend.

Inspired by Hermes-style provider profiles (e.g. ``NvidiaProfile`` owns the
reasoning wire shape), OpenCode model variants (``provider/model#variant``),
and Pi's ``thinkingLevelMap`` (only offer levels the model ladder contains).

A profile answers three questions without live network calls:
- which reasoning wire shape this provider accepts,
- which effort vocabulary to offer in the thinking selector,
- which parallel-tool behaviour the API tolerates.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderProfile:
    """Wire contract for one provider family."""

    name: str
    # reasoning wire: "reasoning_effort" (top-level OpenAI-style),
    # "thinking" (Anthropic-style), "both", or "none".
    reasoning_wire: str = "reasoning_effort"
    allowed_efforts: tuple[str, ...] = ("low", "medium", "high", "max")
    disable_effort: str = "none"
    default_effort: str = "medium"
    allow_parallel_tools: bool = True
    # Long-thinking watchdog hint (chars of reasoning without an answer
    # before the UI surfaces "extended thinking… Esc to stop").
    thinking_watchdog_chars: int = 6_000
    notes: str = ""


_PROFILES: dict[str, ProviderProfile] = {
    "nvidia": ProviderProfile(
        name="nvidia",
        reasoning_wire="reasoning_effort",
        allowed_efforts=("low", "medium", "high", "max"),
        disable_effort="none",
        default_effort="medium",
        allow_parallel_tools=False,
        thinking_watchdog_chars=6_000,
        notes=(
            "NIM cloud rejects extra_body.reasoning/thinking/include_reasoning; "
            "only top-level reasoning_effort gates thinking."
        ),
    ),
    "groq": ProviderProfile(
        name="groq",
        reasoning_wire="reasoning_effort",
        allowed_efforts=("low", "medium", "high"),
        disable_effort="none",
        default_effort="medium",
        notes="Strict OpenAI clone — no extra_body reasoning fields.",
    ),
    "ollama": ProviderProfile(
        name="ollama",
        reasoning_wire="reasoning_effort",
        allowed_efforts=("low", "medium", "high"),
        disable_effort="none",
        default_effort="medium",
        notes="Local OpenAI clone — no extra_body reasoning fields.",
    ),
    "openrouter": ProviderProfile(
        name="openrouter",
        reasoning_wire="both",
        allowed_efforts=("minimal", "low", "medium", "high", "xhigh", "max"),
        disable_effort="none",
        default_effort="medium",
        notes="OpenRouter-style extra_body.reasoning + top-level effort.",
    ),
    "anthropic": ProviderProfile(
        name="anthropic",
        reasoning_wire="thinking",
        allowed_efforts=("low", "medium", "high", "max"),
        disable_effort="none",
        default_effort="medium",
        notes="Anthropic-style thinking blocks.",
    ),
}

_DEFAULT = ProviderProfile(name="default")

_ALIASES = {
    "nim": "nvidia",
    "nvidia-nim": "nvidia",
    "nvidia_nim": "nvidia",
}


def get_profile(provider: str | None) -> ProviderProfile:
    """Return the wire profile for a provider id (never raises)."""
    key = (provider or "").strip().lower()
    key = _ALIASES.get(key, key)
    return _PROFILES.get(key, _DEFAULT)


def normalize_effort(provider: str | None, effort: str) -> str:
    """Clamp an effort token to the provider vocabulary (case-insensitive)."""
    token = (effort or "").strip().lower()
    if not token:
        return ""
    profile = get_profile(provider)
    if token == profile.disable_effort.lower():
        return profile.disable_effort
    for allowed in profile.allowed_efforts:
        if token == allowed.lower():
            return allowed
    return token


def default_effort_for(provider: str | None) -> str:
    return get_profile(provider).default_effort
