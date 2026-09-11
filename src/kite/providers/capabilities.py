"""Model capability metadata — provider-agnostic, driven by live catalog + LiteLLM."""

from __future__ import annotations

from typing import Any

# Substrings that usually indicate non-agent models (embeddings, audio, legacy completion).
_NON_AGENT_HINTS = (
    "embed",
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "dalle",
    "moderation",
    "babbage",
    "davinci",
)

_TOOL_PARAM_NAMES = frozenset({"tools", "tool_choice", "functions", "parallel_tool_calls"})
_TOOL_CAP_KEYS = frozenset({"tools", "function_calling", "tool_use", "tool_calls", "functions"})


def _tools_from_raw(raw: dict[str, Any] | None) -> bool | None:
    """Return True/False when metadata is explicit; None when unknown."""
    if not raw:
        return None
    for key in ("capabilities", "features", "supports"):
        caps = raw.get(key)
        if not isinstance(caps, dict):
            continue
        for name in _TOOL_CAP_KEYS:
            if name not in caps:
                continue
            flag = caps.get(name)
            if flag is False:
                return False
            if flag:
                return True
    try:
        from kite.providers.list_models import RemoteModel

        remote = RemoteModel(id=str(raw.get("id") or ""), raw=raw)
        params = remote.parameter_names()
        if params & _TOOL_PARAM_NAMES:
            return True
    except Exception:
        pass
    return None


def _tools_from_litellm(provider: str, model: str, litellm_model: str) -> bool | None:
    try:
        import litellm
    except Exception:
        return None
    mid = (litellm_model or model or "").strip()
    if not mid:
        return None
    attempts: list[dict[str, Any]] = []
    if provider:
        attempts.append({"custom_llm_provider": provider})
    attempts.append({})
    for kwargs in attempts:
        try:
            params = litellm.get_supported_openai_params(model=mid, **kwargs)
            norm = {str(p).lower().replace("-", "_") for p in params}
            if norm & _TOOL_PARAM_NAMES:
                return True
        except Exception:
            continue
    return None


def model_supports_tools(
    *,
    provider: str = "",
    model: str = "",
    litellm_model: str = "",
    raw: dict[str, Any] | None = None,
) -> bool | None:
    """Best-effort tool-calling support. None = unknown (do not warn)."""
    from_meta = _tools_from_raw(raw)
    if from_meta is not None:
        return from_meta
    from_litellm = _tools_from_litellm(provider, model, litellm_model)
    if from_litellm is not None:
        return from_litellm
    return None


def agent_model_warning(
    model: str,
    *,
    raw: dict[str, Any] | None = None,
    provider: str = "",
    litellm_model: str = "",
) -> str | None:
    """Return a user-visible warning when a model is likely unsuitable for tool-calling agents."""
    name = (model or "").strip()
    if not name:
        return "No model selected — agent mode requires a tool-capable chat model."
    low = name.lower()
    if any(h in low for h in _NON_AGENT_HINTS):
        return (
            f"Model '{name}' may not support tool calling. "
            "Pick a chat/agent model with function or tool support."
        )
    supports = model_supports_tools(provider=provider, model=name, litellm_model=litellm_model, raw=raw)
    if supports is False:
        return f"Model '{name}' reports no tool support in provider metadata."
    # Unknown or supported — no name-based allowlist; any provider/model may work.
    return None


def platform_shell_hint() -> str:
    import sys

    if sys.platform == "win32":
        return (
            "Windows: prefer PowerShell/cmd, `rg` if installed, and Kite tools over Unix-only "
            "assumptions (`sed`, `grep` without path). Use `dir`, `Get-Content`, or `type` when needed."
        )
    return "POSIX: prefer `rg`, `head`, `sed -n`, and Kite tools for inspection."
