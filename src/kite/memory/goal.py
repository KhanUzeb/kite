"""Persistent session goals — Codex-style /goal for long-horizon work."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from kite.config import ensure_home, kite_home
from kite.memory.secure_io import secure_memory_write

_MAX_OBJECTIVE_CHARS = 4000


@dataclass
class SessionGoal:
    objective: str
    status: str = "active"  # active | paused

    @property
    def active(self) -> bool:
        return bool(self.objective.strip()) and self.status == "active"


def _goals_dir() -> Path:
    ensure_home()
    root = kite_home() / "goals"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _goal_path(session_id: str) -> Path:
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session id required for goal")
    return _goals_dir() / f"{sid}.json"


def load_session_goal(session_id: str) -> SessionGoal | None:
    if not session_id:
        return None
    path = _goal_path(session_id)
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(row, dict):
        return None
    objective = str(row.get("objective") or "")[:_MAX_OBJECTIVE_CHARS]
    if not objective.strip():
        return None
    status = str(row.get("status") or "active").lower()
    if status not in {"active", "paused"}:
        status = "active"
    return SessionGoal(objective=objective, status=status)


def save_session_goal(session_id: str, goal: SessionGoal | None) -> None:
    if not session_id:
        raise ValueError("session id required")
    path = _goal_path(session_id)
    if goal is None or not goal.objective.strip():
        if path.is_file():
            path.unlink(missing_ok=True)
        return
    payload = {
        "objective": goal.objective.strip()[:_MAX_OBJECTIVE_CHARS],
        "status": goal.status if goal.status in {"active", "paused"} else "active",
        "updated_at": time.time(),
    }
    secure_memory_write(path, json.dumps(payload, indent=2) + "\n")


def format_goal_section(objective: str) -> str:
    body = (objective or "").strip()[:_MAX_OBJECTIVE_CHARS]
    if not body:
        return ""
    return (
        "# Active goal\n"
        "You are working toward a **persistent goal** that survives interruptions, "
        "provider errors, and budget pauses. Keep going until the goal is verifiably "
        "complete or the user clears it.\n\n"
        f"**Goal:** {body}\n"
    )
