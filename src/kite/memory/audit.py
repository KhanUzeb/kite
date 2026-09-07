"""Append-only audit log for governance and approval trail."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from kite.config import kite_home
from kite.guardrails import redact_secrets


class AuditLog:
    """JSONL audit trail at ~/.kite/audit.jsonl."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (kite_home() / "audit.jsonl")

    def append(self, kind: str, **payload: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row: dict[str, Any] = {"ts": time.time(), "kind": kind}
        for key, val in payload.items():
            if isinstance(val, str):
                row[key], _ = redact_secrets(val)
            else:
                row[key] = val
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")

    def log_approval(self, tool: str, pattern: str, decision: str, **extra: Any) -> None:
        self.append("approval", tool=tool, pattern=pattern, decision=decision, **extra)

    def log_tool(self, tool: str, ok: bool, **extra: Any) -> None:
        self.append("tool", tool=tool, ok=ok, **extra)

    def log_run(self, session_id: str, exit_status: str, **extra: Any) -> None:
        self.append("run", session_id=session_id, exit_status=exit_status, **extra)

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
