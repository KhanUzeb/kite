"""Token estimation + compaction policy (tau context_window, slimmed)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD = 4
TOOL_OVERHEAD = 16
DEFAULT_WINDOW = 128_000
DEFAULT_RESERVE = 16_384
DEFAULT_KEEP_RECENT = 20_000

COMPACTION_PREFIX = "Previous conversation summary:\n"
FACTS_PREFIX = "## Preserved facts\n"


def extract_compaction_facts(messages: list[dict]) -> list[str]:
    """Deterministic bullets to keep across compaction — paths, failures, constraints."""
    paths: list[str] = []
    failures: list[str] = []
    tools: list[str] = []
    for m in messages:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        if isinstance(m.get("content"), list):
            content = " ".join(
                str(p.get("text") or "") for p in m["content"] if isinstance(p, dict)
            )
        extra = m.get("extra") if isinstance(m.get("extra"), dict) else {}
        if extra.get("path"):
            paths.append(str(extra["path"]))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") if isinstance(tc, dict) else {}
            name = str(fn.get("name") or "") if isinstance(fn, dict) else ""
            if name:
                tools.append(name)
        if role == "user" and any(w in content.lower() for w in ("must", "never", "don't", "do not", "important")):
            line = " ".join(content.split())
            if len(line) > 20:
                failures.append(f"constraint: {line[:240]}")
        if any(tok in content.lower() for tok in ("error", "failed", "traceback", "exception")):
            line = " ".join(content.split())
            if len(line) > 30:
                failures.append(line[:280])
    facts: list[str] = []
    if paths:
        uniq = list(dict.fromkeys(paths))[:24]
        facts.append("files: " + ", ".join(uniq))
    if tools:
        uniq_tools = list(dict.fromkeys(tools))[-16:]
        facts.append("tools used: " + ", ".join(uniq_tools))
    for line in failures[:12]:
        facts.append(line)
    return facts


def format_facts_block(facts: list[str]) -> str:
    if not facts:
        return ""
    body = "\n".join(f"- {f}" for f in facts)
    return f"{FACTS_PREFIX}{body}\n\n"


@dataclass(frozen=True)
class ContextUsage:
    total_tokens: int
    system_tokens: int
    message_tokens: int
    tool_tokens: int
    message_count: int
    window: int

    @property
    def remaining(self) -> int:
        return max(0, self.window - self.total_tokens)

    @property
    def ratio(self) -> float:
        return self.total_tokens / self.window if self.window else 0.0


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def estimate_message_tokens(message: dict[str, Any], *, image_token_cost: int = 1024) -> int:
    tokens = MESSAGE_OVERHEAD
    content = message.get("content")
    if isinstance(content, str):
        tokens += estimate_text_tokens(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                ptype = str(part.get("type") or "")
                if ptype == "image_url":
                    tokens += image_token_cost
                else:
                    tokens += estimate_text_tokens(str(part.get("text") or part.get("content") or ""))
            else:
                tokens += estimate_text_tokens(json.dumps(content))
    if message.get("tool_calls"):
        tokens += estimate_text_tokens(json.dumps(message["tool_calls"]))
    if message.get("name"):
        tokens += estimate_text_tokens(str(message["name"]))
    return tokens


def estimate_tool_schema_tokens(schemas: list[dict]) -> int:
    return sum(TOOL_OVERHEAD + estimate_text_tokens(json.dumps(s)) for s in schemas)


def estimate_usage(
    *,
    system: str,
    messages: list[dict],
    tool_schemas: list[dict] | None = None,
    window: int = DEFAULT_WINDOW,
) -> ContextUsage:
    system_tokens = estimate_text_tokens(system)
    # skip system role duplicates in messages list if present
    msg_tokens = 0
    count = 0
    for m in messages:
        if m.get("role") == "exit":
            continue
        msg_tokens += estimate_message_tokens(m)
        count += 1
    tool_tokens = estimate_tool_schema_tokens(tool_schemas or [])
    total = system_tokens + msg_tokens + tool_tokens
    # If first message is system and we also passed system string, avoid double count
    if messages and messages[0].get("role") == "system" and system:
        total -= estimate_text_tokens(str(messages[0].get("content") or ""))
        # still count overhead once
    return ContextUsage(
        total_tokens=max(0, total),
        system_tokens=system_tokens,
        message_tokens=msg_tokens,
        tool_tokens=tool_tokens,
        message_count=count,
        window=window,
    )


def should_compact(usage: ContextUsage, *, reserve: int = DEFAULT_RESERVE) -> bool:
    return usage.window > 0 and usage.total_tokens >= max(1, usage.window - reserve)


def deterministic_summary(messages: list[dict], *, max_chars: int = 6_000) -> str:
    """Cheap offline summary when we don't want an extra LLM call."""
    lines = [f"Compacted {len(messages)} prior message(s)."]
    for i, m in enumerate(messages, 1):
        role = m.get("role", "?")
        content = m.get("content") or ""
        if isinstance(content, list):
            from kite.ui.attach import strip_media_for_summary

            content = strip_media_for_summary(content)
        content = " ".join(str(content).split())
        if m.get("tool_calls"):
            names = ", ".join(tc.get("function", {}).get("name", "?") for tc in m["tool_calls"])
            content = f"{content} [tools: {names}]".strip()
        if len(content) > 240:
            content = content[:237] + "..."
        lines.append(f"{i}. {role}: {content}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 15] + "\n...[truncated]"
    return text


def compact_messages(
    messages: list[dict],
    *,
    keep_recent_tokens: int = DEFAULT_KEEP_RECENT,
    summarizer: Callable | None = None,
    force: bool = False,
) -> list[dict]:
    """Replace older turns with a summary user message; keep recent tail."""
    if len(messages) < 4:
        return messages
    if len(messages) < 6 and not force:
        return messages

    # Always keep leading system message if present
    head: list[dict] = []
    body = list(messages)
    if body and body[0].get("role") == "system":
        head = [body.pop(0)]

    # Walk from end accumulating tokens until keep_recent budget
    kept_rev: list[dict] = []
    budget = 0
    for m in reversed(body):
        t = estimate_message_tokens(m)
        if kept_rev and budget + t > keep_recent_tokens:
            break
        kept_rev.append(m)
        budget += t
    kept = list(reversed(kept_rev))
    dropped = body[: len(body) - len(kept)]
    if not dropped and force and len(body) > 4:
        dropped = body[:-4]
        kept = body[-4:]
    if not dropped:
        return messages

    facts = extract_compaction_facts(dropped)
    facts_block = format_facts_block(facts)
    body_text = summarizer(dropped) if summarizer else deterministic_summary(dropped)
    summary = COMPACTION_PREFIX + facts_block + body_text
    return [*head, {"role": "user", "content": summary, "extra": {"compacted": True, "facts": facts}}, *kept]
