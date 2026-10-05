"""Agent handoff documents — structured context export for another coding agent."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kite.context.window import estimate_usage
from kite.memory.context_checkpoint import save_checkpoint
from kite.memory.continuity import context_section, first_user_text
from kite.memory.session import Session, SessionMeta


@dataclass
class HandoffBundle:
    session_id: str
    markdown: str
    json_path: Path | None
    markdown_path: Path | None
    checkpoint_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "checkpoint_id": self.checkpoint_id,
            "markdown_path": str(self.markdown_path) if self.markdown_path else None,
            "json_path": str(self.json_path) if self.json_path else None,
        }


def _extract_todos(todos: list[dict] | None) -> str:
    if not todos:
        return "(none)"
    lines = [f"- [{t.get('status', 'pending')}] {t.get('content', '')}" for t in todos]
    return "\n".join(lines) or "(none)"


def _mission_from_messages(messages: list[dict], task: str) -> str:
    text = first_user_text(messages)
    if text:
        return text[:2000]
    return task or "(unknown)"


def _context_section(messages: list[dict], *, max_chars: int = 12_000) -> str:
    return context_section(messages, max_chars=max_chars)


def resume_command(session_id: str, message: str = "continue from handoff") -> str:
    """Canonical resume CLI (single format point for handoffs + limit briefs)."""
    return f'kite resume {session_id} "{message}"'


def build_handoff_markdown(
    *,
    meta: SessionMeta,
    messages: list[dict],
    cwd: str,
    todos: list[dict] | None = None,
    checkpoint_id: str,
    provider: str = "",
    model: str = "",
    verification: dict[str, Any] | None = None,
) -> str:
    usage = estimate_usage(system="", messages=messages)
    mission = _mission_from_messages(messages, meta.task)
    ctx = _context_section(messages)
    ver = verification or {}
    ver_lines = ""
    if ver:
        ver_lines = f"\n## Verification\n\n```json\n{json.dumps(ver, indent=2)[:4000]}\n```\n"

    return f"""# Kite Agent Handoff

Generated: {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}

## Resume command

```bash
{resume_command(meta.id)}
# or open REPL:
kite chat --session {meta.id}
```

## Mission

{mission}

## Session

| Field | Value |
|-------|-------|
| session_id | `{meta.id}` |
| checkpoint_id | `{checkpoint_id}` |
| cwd | `{cwd}` |
| provider / model | `{provider or meta.provider}` / `{model or meta.model}` |
| context | {usage.total_tokens:,} / {usage.window:,} tokens ({usage.ratio:.0%}) |
| messages | {len(messages)} |
| label | {meta.label or "—"} |

## Active plan

{_extract_todos(todos)}

## Conversation context

{ctx}
{ver_lines}
## Instructions for the next agent

1. Read this handoff and the checkpoint transcript if you need full history.
2. Stay in the same cwd unless the user directs otherwise.
3. Continue the mission above; do not restart from scratch.
4. Run targeted verification before declaring done.

---
*Handoff from [Kite](https://github.com/KhanUzeb/kite) — checkpoint `{checkpoint_id}`*
"""


def secure_handoff_write(path: Path, text: str) -> None:
    """Atomic + owner-only handoff file write."""
    from kite.memory.session_policy import secure_session_file
    from kite.util.atomic import atomic_write_text

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    secure_session_file(path)


def write_handoff(
    *,
    session: Session,
    cwd: str,
    todos: list[dict] | None = None,
    out_dir: str | Path | None = None,
    label: str = "handoff",
    provider: str = "",
    model: str = "",
    verification: dict[str, Any] | None = None,
    system: str = "",
) -> HandoffBundle:
    """Save checkpoint + markdown + JSON handoff bundle."""
    from kite.memory.secure_io import storage_id
    from kite.memory.session_policy import prepare_persisted_value

    sid = storage_id(session.id, label="session id")

    safe_messages = prepare_persisted_value(list(session.messages))
    if not isinstance(safe_messages, list):
        safe_messages = list(session.messages)
    cp = save_checkpoint(
        session_id=session.id,
        messages=safe_messages,
        cwd=cwd,
        label=label,
        reason="manual",
        todos=todos,
        meta=session.meta.to_dict(),
        system=system,
    )
    md = build_handoff_markdown(
        meta=session.meta,
        messages=safe_messages,
        cwd=cwd,
        todos=todos,
        checkpoint_id=cp.id,
        provider=provider,
        model=model,
        verification=verification,
    )
    base = Path(out_dir or cwd).expanduser().resolve()
    kite_dir = base / ".kite"
    kite_dir.mkdir(parents=True, exist_ok=True)
    md_path = kite_dir / f"handoff-{sid}.md"
    json_path = kite_dir / f"handoff-{sid}.json"
    # A handoff is read by another agent (often after this process is gone), so
    # both files must land whole: a torn write leaves a half-parsed bundle that
    # cannot be restored from at all.
    secure_handoff_write(md_path, md)
    payload = prepare_persisted_value({
        "format": "kite-handoff-v1",
        "generated_at": time.time(),
        "checkpoint": cp.to_dict(),
        "resume": {
            "session_id": session.id,
            "checkpoint_id": cp.id,
            "cwd": cwd,
            "command": f"kite resume {session.id}",
        },
        "markdown_excerpt": md[:8000],
    })
    secure_handoff_write(json_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return HandoffBundle(
        session_id=session.id,
        markdown=md,
        markdown_path=md_path,
        json_path=json_path,
        checkpoint_id=cp.id,
    )
