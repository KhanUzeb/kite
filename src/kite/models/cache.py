"""Prompt cache — pi-style prefix caching for cost-effective multi-turn runs.

Applies provider-native cache breakpoints (Anthropic cache_control) and tracks
cache_read / cache_creation / cached_tokens from API usage for the status line.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

_CACHE_PROVIDERS = frozenset({"anthropic", "openrouter", "azure", "bedrock"})


@dataclass
class CacheStats:
    """Accumulated cache usage for the session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cached_tokens: int = 0  # OpenAI-style prompt_tokens_details.cached_tokens
    calls: int = 0

    @property
    def cache_hit_tokens(self) -> int:
        return self.cache_read_tokens or self.cached_tokens

    @property
    def hit_ratio(self) -> float:
        total_in = self.prompt_tokens + self.cache_read_tokens + self.cache_creation_tokens
        if total_in <= 0:
            return 0.0
        return self.cache_hit_tokens / total_in

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "hit_ratio": round(self.hit_ratio, 3),
            "calls": self.calls,
        }


def _tail_signature(messages: list[dict]) -> int:
    """Fingerprint of the stable prefix + recent-tail boundary (not full length).

    Breakpoints only cover the stable prefix (system / compaction summary), so appending tail turns
    must not invalidate the prepared prefix. Hash the head (first system/user message) and the tail
    boundary (last two messages' roles + snippets) instead of the conversation length.
    """
    if not messages:
        return 0
    head = ""
    for m in messages[:3]:
        if m.get("role") in {"system", "user"}:
            content = m.get("content")
            head = content[:240] if isinstance(content, str) else str(content)[:240]
            break
    tail: list[tuple[str | None, str]] = []
    for m in messages[-2:]:
        content = m.get("content")
        snippet = content[:240] if isinstance(content, str) else str(content)[:240]
        tail.append((m.get("role"), snippet))
    return hash((head, tuple(tail)))


def _hash_prefix(messages: list[dict]) -> str:
    """Stable hash of the stable prefix (system + first user if compacted)."""
    parts: list[str] = []
    for m in messages[:3]:
        if m.get("role") in {"system", "user"}:
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c[:4000])
    raw = "\n---\n".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_key(messages: list[dict]) -> tuple[str, int]:
    """Single conversation key: stable prefix hash + tail signature.

    One equality check preserves the old dual ``prefix == and tail ==``
    hit behavior exactly.
    """
    return (_hash_prefix(messages), _tail_signature(messages))


def _supports_breakpoints(provider: str) -> bool:
    p = (provider or "").lower()
    for x in _CACHE_PROVIDERS:
        if p == x or p.endswith(f"/{x}") or p.startswith(f"{x}/"):
            return True
    return False


def apply_cache_breakpoints(messages: list[dict], *, provider: str, enabled: bool = True) -> list[dict]:
    """Add Anthropic-style cache_control on stable prefix messages.

    Layout follows the token-efficiency guide: ``tools → system → [break] →
    setup/summary → [break] → conversation``. Up to two breakpoints: one on the
    system prompt and one on the compaction summary (the stable setup block).
    Volatile conversation turns never get a breakpoint.
    """
    if not enabled or not _supports_breakpoints(provider):
        return messages

    out: list[dict] = []
    breakpoints = 0
    for m in messages:
        msg = dict(m)
        role = msg.get("role")
        extra = m.get("extra") if isinstance(m.get("extra"), dict) else {}
        if breakpoints == 0 and role == "system":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                msg["content"] = [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                breakpoints += 1
        elif breakpoints >= 1 and breakpoints < 2 and role == "user" and isinstance(msg.get("content"), str):
            text = str(msg["content"])
            is_setup = bool(extra.get("setup")) or text.startswith("# Setup")
            is_summary = text.startswith("Previous conversation summary:")
            if is_setup or is_summary:
                msg["content"] = [
                    {
                        "type": "text",
                        "text": text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                breakpoints += 1
        elif breakpoints == 0 and role == "user" and isinstance(msg.get("content"), str):
            text = str(msg["content"])
            if text.startswith("Previous conversation summary:"):
                msg["content"] = [
                    {
                        "type": "text",
                        "text": text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                breakpoints += 1
        out.append(msg)
    return out


def parse_cache_usage(usage: Any, hidden: dict[str, Any] | None = None) -> dict[str, int]:
    """Extract cache fields from LiteLLM usage / hidden params."""
    out = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cached_tokens": 0,
    }
    if usage is None:
        return out

    out["prompt_tokens"] = int(getattr(usage, "prompt_tokens", 0) or 0)
    out["completion_tokens"] = int(getattr(usage, "completion_tokens", 0) or 0)

    # Anthropic
    for attr in ("cache_read_input_tokens", "cache_creation_input_tokens"):
        val = getattr(usage, attr, None)
        if val:
            key = "cache_read_tokens" if "read" in attr else "cache_creation_tokens"
            out[key] = int(val)

    # OpenAI prompt_tokens_details
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", None)
        if cached is None and isinstance(details, dict):
            cached = details.get("cached_tokens")
        if cached:
            out["cached_tokens"] = int(cached)

    # LiteLLM hidden / provider extras
    hidden = hidden or {}
    if isinstance(hidden, dict):
        for key, target in (
            ("cache_read_input_tokens", "cache_read_tokens"),
            ("cache_creation_input_tokens", "cache_creation_tokens"),
            ("cached_tokens", "cached_tokens"),
        ):
            if hidden.get(key):
                out[target] = int(hidden[key])

    return out


@dataclass
class PromptCacheManager:
    """Session-scoped prompt cache tracker (pi-style prefix stability)."""

    provider: str
    enabled: bool = True
    session: CacheStats = field(default_factory=CacheStats)
    _cache_key_val: tuple[str, int] | None = field(default=None, init=False, repr=False)
    _prepared_messages: list[dict] | None = field(default=None, init=False)

    # Backward-compat aliases for the pre-trim dual fields.
    @property
    def _prefix_hash(self) -> str:
        return self._cache_key_val[0] if self._cache_key_val else ""

    @_prefix_hash.setter
    def _prefix_hash(self, value: str) -> None:
        tail = self._cache_key_val[1] if self._cache_key_val else 0
        self._cache_key_val = (value, tail)

    @property
    def _tail_sig(self) -> int:
        return self._cache_key_val[1] if self._cache_key_val else 0

    @_tail_sig.setter
    def _tail_sig(self, value: int) -> None:
        prefix = self._cache_key_val[0] if self._cache_key_val else ""
        self._cache_key_val = (prefix, value)

    def prepare(self, messages: list[dict]) -> list[dict]:
        key = _cache_key(messages)
        if key == self._cache_key_val and self._prepared_messages is not None:
            return self._prepared_messages
        self._cache_key_val = key
        self._prepared_messages = apply_cache_breakpoints(
            messages, provider=self.provider, enabled=self.enabled
        )
        return self._prepared_messages

    def record(self, usage: Any, hidden: dict[str, Any] | None = None) -> CacheStats:
        parsed = parse_cache_usage(usage, hidden)
        self.session.prompt_tokens += parsed["prompt_tokens"]
        self.session.completion_tokens += parsed["completion_tokens"]
        self.session.cache_read_tokens += parsed["cache_read_tokens"]
        self.session.cache_creation_tokens += parsed["cache_creation_tokens"]
        self.session.cached_tokens += parsed["cached_tokens"]
        self.session.calls += 1
        return CacheStats(**parsed)

    def last_hit(self, parsed: dict[str, int]) -> bool:
        return bool(parsed.get("cache_read_tokens") or parsed.get("cached_tokens"))

    def summary(self) -> dict[str, Any]:
        return {**self.session.to_dict(), "prefix_hash": self._prefix_hash}
