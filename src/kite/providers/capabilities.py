"""Model capability metadata for agent suitability."""

from __future__ import annotations

import re

# Substrings that usually indicate non-agent models (embeddings, audio, legacy completion).
_NON_AGENT_HINTS = (
    "embed",
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "moderation",
    "babbage",
    "davinci",
    "instruct",  # legacy completion-only families
)

_TOOL_REQUIRED = re.compile(r"(?i)(gpt-4|claude|gemini|llama|mistral|qwen|deepseek|command)")


def agent_model_warning(model: str, *, raw: dict | None = None) -> str | None:
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
    if raw:
        caps = raw.get("capabilities") or raw.get("features") or {}
        if isinstance(caps, dict) and caps.get("tools") is False:
            return f"Model '{name}' reports no tool support in provider metadata."
    if not _TOOL_REQUIRED.search(name) and "instruct" not in low:
        return None
    return None


def platform_shell_hint() -> str:
    import sys

    if sys.platform == "win32":
        return (
            "Windows: prefer PowerShell/cmd, `rg` if installed, and Kite tools over Unix-only "
            "assumptions (`sed`, `grep` without path). Use `dir`, `Get-Content`, or `type` when needed."
        )
    return "POSIX: prefer `rg`, `head`, `sed -n`, and Kite tools for inspection."
