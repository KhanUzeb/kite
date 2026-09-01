"""Aggregate session / trajectory stats for dashboard and long-task introspection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.config import kite_home
from kite.memory.session import _read_session_meta, sessions_dir


@dataclass
class SessionStats:
    session_id: str
    created_at: float = 0.0
    updated_at: float = 0.0
    duration_s: float = 0.0
    provider: str = ""
    model: str = ""
    task: str = ""
    label: str = ""
    exit_status: str = ""
    tool_calls: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    api_calls: int = 0
    cost: float = 0.0
    estimated_tokens: int = 0
    cache_hit_tokens: int = 0
    compaction_count: int = 0
    turn_count: int = 0
    message_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "duration_s": round(self.duration_s, 1),
            "provider": self.provider,
            "model": self.model,
            "task": self.task,
            "label": self.label,
            "exit_status": self.exit_status,
            "tool_calls": self.tool_calls,
            "tool_counts": dict(self.tool_counts),
            "api_calls": self.api_calls,
            "cost": round(self.cost, 4),
            "estimated_tokens": self.estimated_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "compaction_count": self.compaction_count,
            "turn_count": self.turn_count,
            "message_count": self.message_count,
        }


def _stats_sidecar(session_id: str) -> Path:
    return sessions_dir() / f"{session_id}.stats.json"


def save_session_stats(stats: SessionStats) -> Path:
    path = _stats_sidecar(stats.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats.to_dict(), indent=2), encoding="utf-8")
    return path


def load_session_stats(session_id: str) -> SessionStats | None:
    path = _stats_sidecar(session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionStats(
            session_id=str(data.get("session_id") or session_id),
            created_at=float(data.get("created_at") or 0),
            updated_at=float(data.get("updated_at") or 0),
            duration_s=float(data.get("duration_s") or 0),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            task=str(data.get("task") or ""),
            label=str(data.get("label") or ""),
            exit_status=str(data.get("exit_status") or ""),
            tool_calls=int(data.get("tool_calls") or 0),
            tool_counts=dict(data.get("tool_counts") or {}),
            api_calls=int(data.get("api_calls") or 0),
            cost=float(data.get("cost") or 0),
            estimated_tokens=int(data.get("estimated_tokens") or 0),
            cache_hit_tokens=int(data.get("cache_hit_tokens") or 0),
            compaction_count=int(data.get("compaction_count") or 0),
            turn_count=int(data.get("turn_count") or 0),
            message_count=int(data.get("message_count") or 0),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _trajectory_path(session_id: str) -> Path:
    return kite_home() / "trajectories" / f"{session_id}.json"


def _merge_trajectory(stats: SessionStats) -> None:
    path = _trajectory_path(stats.session_id)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = data.get("info") or {}
        model_stats = info.get("model_stats") or {}
        ctx = info.get("context") or {}
        stats.api_calls = int(model_stats.get("api_calls") or stats.api_calls)
        stats.cost = float(model_stats.get("instance_cost") or stats.cost)
        if ctx.get("estimated_tokens"):
            stats.estimated_tokens = int(ctx["estimated_tokens"])
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return


def scan_session_file(path: Path) -> SessionStats | None:
    meta = _read_session_meta(path)
    if meta is None:
        return None
    stats = SessionStats(
        session_id=meta.id,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
        duration_s=max(0.0, meta.updated_at - meta.created_at),
        provider=meta.provider,
        model=meta.model,
        task=meta.task,
        label=meta.label,
        exit_status=meta.exit_status,
    )
    tool_counts: dict[str, int] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                rtype = row.get("type")
                if rtype == "message":
                    stats.message_count += 1
                elif rtype == "event":
                    kind = str(row.get("kind") or "")
                    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                    if kind == "tool_end":
                        stats.tool_calls += 1
                        tool = str(payload.get("tool") or "unknown")
                        tool_counts[tool] = tool_counts.get(tool, 0) + 1
                    elif kind == "turn_start":
                        stats.turn_count += 1
                    elif kind == "compact":
                        stats.compaction_count += 1
                    elif kind == "cache_hit":
                        hits = int(payload.get("cache_read") or payload.get("cached") or 0)
                        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
                        if not hits and session:
                            hits = int(session.get("cache_hit_tokens") or 0)
                        stats.cache_hit_tokens += hits
    except (OSError, json.JSONDecodeError):
        pass
    stats.tool_counts = tool_counts

    sidecar = load_session_stats(meta.id)
    if sidecar is not None:
        if sidecar.tool_calls > stats.tool_calls:
            stats.tool_calls = sidecar.tool_calls
        if sidecar.tool_counts:
            for tool, count in sidecar.tool_counts.items():
                stats.tool_counts[tool] = max(stats.tool_counts.get(tool, 0), count)
        stats.api_calls = sidecar.api_calls or stats.api_calls
        stats.cost = sidecar.cost or stats.cost
        stats.estimated_tokens = sidecar.estimated_tokens or stats.estimated_tokens
        stats.cache_hit_tokens = max(stats.cache_hit_tokens, sidecar.cache_hit_tokens)
        stats.turn_count = max(stats.turn_count, sidecar.turn_count)
        stats.compaction_count = max(stats.compaction_count, sidecar.compaction_count)
    _merge_trajectory(stats)
    return stats


def list_session_stats(*, limit: int = 500) -> list[SessionStats]:
    rows: list[SessionStats] = []
    directory = sessions_dir()
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name.endswith(".stats.json"):
            continue
        row = scan_session_file(path)
        if row is not None:
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


@dataclass
class DashboardSummary:
    session_count: int = 0
    total_tool_calls: int = 0
    total_api_calls: int = 0
    total_cost: float = 0.0
    total_estimated_tokens: int = 0
    total_cache_hits: int = 0
    tool_totals: dict[str, int] = field(default_factory=dict)
    longest_sessions: list[SessionStats] = field(default_factory=list)
    recent_sessions: list[SessionStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_count": self.session_count,
            "total_tool_calls": self.total_tool_calls,
            "total_api_calls": self.total_api_calls,
            "total_cost": round(self.total_cost, 4),
            "total_estimated_tokens": self.total_estimated_tokens,
            "total_cache_hits": self.total_cache_hits,
            "tool_totals": dict(self.tool_totals),
            "longest_sessions": [s.to_dict() for s in self.longest_sessions[:8]],
            "recent_sessions": [s.to_dict() for s in self.recent_sessions[:8]],
        }


def build_dashboard_summary(*, limit: int = 200) -> DashboardSummary:
    sessions = list_session_stats(limit=limit)
    summary = DashboardSummary(session_count=len(sessions))
    for s in sessions:
        summary.total_tool_calls += s.tool_calls
        summary.total_api_calls += s.api_calls
        summary.total_cost += s.cost
        summary.total_estimated_tokens += s.estimated_tokens
        summary.total_cache_hits += s.cache_hit_tokens
        for tool, count in s.tool_counts.items():
            summary.tool_totals[tool] = summary.tool_totals.get(tool, 0) + count
    summary.longest_sessions = sorted(sessions, key=lambda x: x.duration_s, reverse=True)[:8]
    summary.recent_sessions = sorted(sessions, key=lambda x: x.updated_at, reverse=True)[:8]
    return summary
