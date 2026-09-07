"""Token estimation + compaction policy (tau context_window, slimmed)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD = 4
TOOL_OVERHEAD = 16
DEFAULT_WINDOW = 128_000
DEFAULT_RESERVE = 12_288
DEFAULT_KEEP_RECENT = 12_000
DEFAULT_TOOL_HISTORY_CHARS = 2_400

COMPACTION_PREFIX = "Previous conversation summary:\n"
FACTS_PREFIX = "## Preserved facts\n"


def extract_compaction_facts(messages: list[dict]) -> list[str]:
    """Deterministic bullets to keep across compaction — paths, failures, constraints."""
    paths: list[str] = []
    failures: list[str] = []
    tools: list[str] = []
    commands: list[str] = []
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
            if name == "bash":
                try:
                    import json as _json

                    args = _json.loads(str(fn.get("arguments") or "{}"))
                    cmd = str(args.get("command") or "").strip().replace("\n", " ")
                    if cmd:
                        commands.append(cmd[:160])
                except (TypeError, ValueError, _json.JSONDecodeError):
                    pass
        if role == "tool" and content:
            for line in content.splitlines()[:8]:
                low = line.lower()
                if " passed" in low or " failed" in low or "error" in low:
                    failures.append(line.strip()[:200])
                    break
            for token in content.replace("\\", "/").split():
                if "/" in token and "." in token and len(token) < 120:
                    if token.endswith((".py", ".ts", ".tsx", ".js", ".md", ".toml", ".rs", ".go")):
                        paths.append(token.strip("`'\"(),"))
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
    if commands:
        uniq_cmd = list(dict.fromkeys(commands))[-8:]
        facts.append("bash: " + " | ".join(uniq_cmd))
    if tools:
        uniq_tools = list(dict.fromkeys(tools))[-16:]
        facts.append("tools used: " + ", ".join(uniq_tools))
    for line in failures[:12]:
        if line not in facts:
            facts.append(line)
    return facts


def scale_keep_recent_tokens(window: int, configured: int) -> int:
    """Cap recent-tail budget relative to model context window."""
    if window <= 0:
        return configured
    relative = max(4_000, int(window * 0.12))
    return min(configured, relative)


def _message_content_text(message: dict) -> str:
    content = message.get("content") or ""
    if isinstance(content, list):
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return str(content)


def trim_stale_tool_messages(
    messages: list[dict],
    *,
    max_tool_chars: int = DEFAULT_TOOL_HISTORY_CHARS,
    keep_recent_segments: int = 3,
) -> list[dict]:
    """Shrink older tool outputs before compaction — recent turns stay full."""
    if len(messages) < 4:
        return messages
    head: list[dict] = []
    body = list(messages)
    if body and body[0].get("role") == "system":
        head = [body.pop(0)]
    segments = _message_segments(body)
    if len(segments) <= keep_recent_segments:
        return messages
    cutoff = len(segments) - keep_recent_segments
    out: list[dict] = []
    for idx, segment in enumerate(segments):
        for m in segment:
            if idx >= cutoff or m.get("role") != "tool":
                out.append(m)
                continue
            text = _message_content_text(m)
            if len(text) <= max_tool_chars:
                out.append(m)
                continue
            lines = text.splitlines()
            if len(lines) > 20:
                preview = "\n".join(lines[:6]) + f"\n...[trimmed {len(lines) - 6} lines]...\n" + lines[-2]
            else:
                preview = text[: max_tool_chars - 20] + "\n...[trimmed]..."
            trimmed = dict(m)
            trimmed["content"] = preview
            extra = dict(trimmed.get("extra") or {})
            extra["trimmed"] = True
            trimmed["extra"] = extra
            out.append(trimmed)
    return [*head, *out]


def coalesce_compaction_summaries(messages: list[dict]) -> list[dict]:
    """Merge stacked compaction summary user messages into one."""
    if len(messages) < 3:
        return messages
    head: list[dict] = []
    body = list(messages)
    if body and body[0].get("role") == "system":
        head = [body.pop(0)]
    merged: list[dict] = []
    pending: list[str] = []
    for m in body:
        content = _message_content_text(m)
        extra = m.get("extra") if isinstance(m.get("extra"), dict) else {}
        if m.get("role") == "user" and extra.get("compacted") and content.startswith(COMPACTION_PREFIX):
            pending.append(content.removeprefix(COMPACTION_PREFIX).strip())
            continue
        if pending:
            merged.append(
                {
                    "role": "user",
                    "content": COMPACTION_PREFIX + "\n\n---\n\n".join(pending),
                    "extra": {"compacted": True, "merged": len(pending)},
                }
            )
            pending.clear()
        merged.append(m)
    if pending:
        merged.append(
            {
                "role": "user",
                "content": COMPACTION_PREFIX + "\n\n---\n\n".join(pending),
                "extra": {"compacted": True, "merged": len(pending)},
            }
        )
    return [*head, *merged]


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
    msg_tokens = 0
    count = 0
    for m in messages:
        if m.get("role") == "exit":
            continue
        msg_tokens += estimate_message_tokens(m)
        count += 1
    tool_tokens = estimate_tool_schema_tokens(tool_schemas or [])
    total = system_tokens + msg_tokens + tool_tokens
    if messages and messages[0].get("role") == "system" and system:
        total -= estimate_text_tokens(str(messages[0].get("content") or ""))
    return ContextUsage(
        total_tokens=max(0, total),
        system_tokens=system_tokens,
        message_tokens=msg_tokens,
        tool_tokens=tool_tokens,
        message_count=count,
        window=window,
    )


DEFAULT_COMPACT_RATIO = 0.75


def should_compact(
    usage: ContextUsage,
    *,
    reserve: int = DEFAULT_RESERVE,
    ratio: float = DEFAULT_COMPACT_RATIO,
) -> bool:
    if usage.window > 0 and usage.ratio >= ratio:
        return True
    return usage.window > 0 and usage.total_tokens >= max(1, usage.window - reserve)


def _message_segments(messages: list[dict]) -> list[list[dict]]:
    """Group assistant tool_calls with their following tool results."""
    segments: list[list[dict]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            seg = [m]
            i += 1
            while i < len(messages) and messages[i].get("role") == "tool":
                seg.append(messages[i])
                i += 1
            segments.append(seg)
        else:
            segments.append([m])
            i += 1
    return segments


def deterministic_summary(messages: list[dict], *, max_chars: int = 4_800) -> str:
    """Cheap offline summary when we don't want an extra LLM call."""
    segments = _message_segments(messages)
    lines = [f"Compacted {len(messages)} message(s) across {len(segments)} turn(s)."]
    for i, segment in enumerate(segments, 1):
        seen_roles: list[str] = []
        for m in segment:
            r = str(m.get("role") or "?")
            if r not in seen_roles:
                seen_roles.append(r)
        roles = "+".join(seen_roles)
        preview_parts: list[str] = []
        for m in segment:
            role = m.get("role", "?")
            content = _message_content_text(m)
            if m.get("tool_calls"):
                names = ", ".join(tc.get("function", {}).get("name", "?") for tc in m["tool_calls"])
                preview_parts.append(f"{role} [tools: {names}]")
            elif role == "tool":
                first = content.splitlines()[0] if content else ""
                preview_parts.append(f"tool: {first[:120]}" if first else "tool: (empty)")
            elif content.strip():
                text = " ".join(content.split())
                preview_parts.append(f"{role}: {text[:140]}")
        if preview_parts:
            lines.append(f"{i}. ({roles}) {' · '.join(preview_parts)}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 15] + "\n...[truncated]"
    return text


def compact_messages(
    messages: list[dict],
    *,
    keep_recent_tokens: int = DEFAULT_KEEP_RECENT,
    window: int = 0,
    summarizer: Callable | None = None,
    force: bool = False,
    extra_facts: list[str] | None = None,
    trim_tools: bool = True,
) -> list[dict]:
    """Replace older turns with a summary user message; keep recent tail."""
    messages = coalesce_compaction_summaries(messages)
    if trim_tools:
        messages = trim_stale_tool_messages(messages)
    if window > 0:
        keep_recent_tokens = scale_keep_recent_tokens(window, keep_recent_tokens)
    if len(messages) < 4:
        return messages
    if len(messages) < 6 and not force:
        return messages

    head: list[dict] = []
    body = list(messages)
    if body and body[0].get("role") == "system":
        head = [body.pop(0)]

    kept_rev: list[dict] = []
    budget = 0
    for segment in reversed(_message_segments(body)):
        seg_tokens = sum(estimate_message_tokens(m) for m in segment)
        if kept_rev and budget + seg_tokens > keep_recent_tokens:
            break
        kept_rev.extend(reversed(segment))
        budget += seg_tokens
    kept = list(reversed(kept_rev))
    dropped = body[: len(body) - len(kept)]
    if not dropped and force and len(body) > 4:
        dropped = body[:-4]
        kept = body[-4:]
    if not dropped:
        return messages

    facts = extract_compaction_facts(dropped)
    for fact in extra_facts or []:
        line = fact.strip()
        if line and line not in facts:
            facts.append(line)
    facts_block = format_facts_block(facts)
    body_text = summarizer(dropped) if summarizer else deterministic_summary(dropped)
    summary = COMPACTION_PREFIX + facts_block + body_text
    return [*head, {"role": "user", "content": summary, "extra": {"compacted": True, "facts": facts}}, *kept]
