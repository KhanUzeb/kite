"""Aggregate session / trajectory stats for per-user dashboard and introspection."""

from __future__ import annotations

import getpass
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kite.config import UserConfig, kite_home
from kite.memory.session import _read_session_meta, sessions_dir

_FAILED_STATUSES = frozenset(
    {
        "Error",
        "Stalled",
        "ProviderFault",
        "Denied",
        "Interrupted",
        "LimitsExceeded",
        "TimeExceeded",
        "RepeatedFormatError",
    }
)


@dataclass
class UserDashboardProfile:
    """Identity + defaults for the local Kite user (one dashboard per ~/.kite home)."""

    username: str
    kite_home: str
    default_provider: str
    default_model: str
    step_limit: int
    cost_limit: float
    sessions_dir: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "kite_home": self.kite_home,
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "step_limit": self.step_limit,
            "cost_limit": self.cost_limit,
            "sessions_dir": self.sessions_dir,
        }


def build_user_profile() -> UserDashboardProfile:
    cfg = UserConfig.load()
    home = kite_home()
    return UserDashboardProfile(
        username=getpass.getuser(),
        kite_home=str(home),
        default_provider=cfg.default_provider,
        default_model=str(cfg.default_model or "—"),
        step_limit=cfg.step_limit,
        cost_limit=cfg.cost_limit,
        sessions_dir=str(sessions_dir()),
    )


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
    cwd: str = ""
    exit_status: str = ""
    mode: str = ""
    approval: str = ""
    verification_status: str = ""
    last_error: str = ""
    tool_calls: int = 0
    tool_counts: dict[str, int] = field(default_factory=dict)
    tool_failures: int = 0
    tool_blocked: int = 0
    write_edits: int = 0
    bash_calls: int = 0
    api_calls: int = 0
    cost: float = 0.0
    estimated_tokens: int = 0
    cache_hit_tokens: int = 0
    compaction_count: int = 0
    turn_count: int = 0
    message_count: int = 0
    subagent_runs: int = 0
    interrupts: int = 0
    checkpoints: int = 0
    approvals: int = 0

    @property
    def is_active(self) -> bool:
        return not (self.exit_status or "").strip()

    @property
    def is_failed(self) -> bool:
        return (self.exit_status or "") in _FAILED_STATUSES

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
            "cwd": self.cwd,
            "exit_status": self.exit_status,
            "mode": self.mode,
            "approval": self.approval,
            "verification_status": self.verification_status,
            "last_error": self.last_error,
            "tool_calls": self.tool_calls,
            "tool_counts": dict(self.tool_counts),
            "tool_failures": self.tool_failures,
            "tool_blocked": self.tool_blocked,
            "write_edits": self.write_edits,
            "bash_calls": self.bash_calls,
            "api_calls": self.api_calls,
            "cost": round(self.cost, 4),
            "estimated_tokens": self.estimated_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "compaction_count": self.compaction_count,
            "turn_count": self.turn_count,
            "message_count": self.message_count,
            "subagent_runs": self.subagent_runs,
            "interrupts": self.interrupts,
            "checkpoints": self.checkpoints,
            "approvals": self.approvals,
            "is_active": self.is_active,
            "is_failed": self.is_failed,
        }


def _stats_sidecar(session_id: str) -> Path:
    return sessions_dir() / f"{session_id}.stats.json"


def _stats_from_dict(data: dict[str, Any], *, session_id: str) -> SessionStats:
    return SessionStats(
        session_id=str(data.get("session_id") or session_id),
        created_at=float(data.get("created_at") or 0),
        updated_at=float(data.get("updated_at") or 0),
        duration_s=float(data.get("duration_s") or 0),
        provider=str(data.get("provider") or ""),
        model=str(data.get("model") or ""),
        task=str(data.get("task") or ""),
        label=str(data.get("label") or ""),
        cwd=str(data.get("cwd") or ""),
        exit_status=str(data.get("exit_status") or ""),
        mode=str(data.get("mode") or ""),
        approval=str(data.get("approval") or ""),
        verification_status=str(data.get("verification_status") or ""),
        last_error=str(data.get("last_error") or ""),
        tool_calls=int(data.get("tool_calls") or 0),
        tool_counts=dict(data.get("tool_counts") or {}),
        tool_failures=int(data.get("tool_failures") or 0),
        tool_blocked=int(data.get("tool_blocked") or 0),
        write_edits=int(data.get("write_edits") or 0),
        bash_calls=int(data.get("bash_calls") or 0),
        api_calls=int(data.get("api_calls") or 0),
        cost=float(data.get("cost") or 0),
        estimated_tokens=int(data.get("estimated_tokens") or 0),
        cache_hit_tokens=int(data.get("cache_hit_tokens") or 0),
        compaction_count=int(data.get("compaction_count") or 0),
        turn_count=int(data.get("turn_count") or 0),
        message_count=int(data.get("message_count") or 0),
        subagent_runs=int(data.get("subagent_runs") or 0),
        interrupts=int(data.get("interrupts") or 0),
        checkpoints=int(data.get("checkpoints") or 0),
        approvals=int(data.get("approvals") or 0),
    )


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
        return _stats_from_dict(data, session_id=session_id)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _merge_sidecar(stats: SessionStats, sidecar: SessionStats) -> None:
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
    stats.message_count = max(stats.message_count, sidecar.message_count)
    for attr in (
        "exit_status",
        "mode",
        "approval",
        "verification_status",
        "last_error",
        "cwd",
        "tool_failures",
        "tool_blocked",
        "write_edits",
        "bash_calls",
        "subagent_runs",
        "interrupts",
        "checkpoints",
        "approvals",
    ):
        val = getattr(sidecar, attr)
        if val and not getattr(stats, attr):
            setattr(stats, attr, val)


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


def _apply_event(stats: SessionStats, kind: str, payload: dict[str, Any]) -> None:
    if kind == "tool_end":
        stats.tool_calls += 1
        tool = str(payload.get("tool") or "unknown")
        stats.tool_counts[tool] = stats.tool_counts.get(tool, 0) + 1
        if not payload.get("ok", True):
            stats.tool_failures += 1
        if payload.get("blocked"):
            stats.tool_blocked += 1
        if tool in {"write", "edit"}:
            stats.write_edits += 1
        if tool == "bash":
            stats.bash_calls += 1
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
    elif kind == "agent_start":
        if payload.get("mode"):
            stats.mode = str(payload["mode"])
        if payload.get("approval"):
            stats.approval = str(payload["approval"])
    elif kind == "agent_end":
        if payload.get("exit_status"):
            stats.exit_status = str(payload["exit_status"])
        if payload.get("verification_status"):
            stats.verification_status = str(payload["verification_status"])
        err = str(payload.get("error") or "").strip()
        if err:
            stats.last_error = err[:240]
    elif kind == "interrupt":
        stats.interrupts += 1
    elif kind == "subagent_start":
        stats.subagent_runs += 1
    elif kind == "checkpoint":
        stats.checkpoints += 1
    elif kind == "approval":
        stats.approvals += 1


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
        cwd=meta.cwd,
        exit_status=meta.exit_status,
    )
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                rtype = row.get("type")
                if rtype == "message":
                    stats.message_count += 1
                elif rtype == "context_checkpoint":
                    stats.checkpoints += 1
                elif rtype == "event":
                    kind = str(row.get("kind") or "")
                    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                    _apply_event(stats, kind, payload)
    except (OSError, json.JSONDecodeError):
        pass

    sidecar = load_session_stats(meta.id)
    if sidecar is not None:
        _merge_sidecar(stats, sidecar)
    _merge_trajectory(stats)
    return stats


def list_session_events(path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """Recent durable events for session drill-down."""
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("type") != "event":
                    continue
                rows.append(
                    {
                        "ts": float(row.get("ts") or 0),
                        "kind": str(row.get("kind") or ""),
                        "payload": row.get("payload") if isinstance(row.get("payload"), dict) else {},
                    }
                )
    except (OSError, json.JSONDecodeError):
        return []
    return rows[-limit:]


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
    user: UserDashboardProfile = field(default_factory=build_user_profile)
    session_count: int = 0
    active_sessions: int = 0
    failed_sessions_count: int = 0
    completed_sessions: int = 0
    sessions_last_24h: int = 0
    cost_last_24h: float = 0.0
    total_tool_calls: int = 0
    total_api_calls: int = 0
    total_cost: float = 0.0
    total_estimated_tokens: int = 0
    total_cache_hits: int = 0
    total_subagents: int = 0
    total_write_edits: int = 0
    avg_duration_s: float = 0.0
    status_counts: dict[str, int] = field(default_factory=dict)
    provider_totals: dict[str, int] = field(default_factory=dict)
    model_totals: dict[str, int] = field(default_factory=dict)
    tool_totals: dict[str, int] = field(default_factory=dict)
    longest_sessions: list[SessionStats] = field(default_factory=list)
    recent_sessions: list[SessionStats] = field(default_factory=list)
    highest_cost_sessions: list[SessionStats] = field(default_factory=list)
    attention_sessions: list[SessionStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user.to_dict(),
            "session_count": self.session_count,
            "active_sessions": self.active_sessions,
            "failed_sessions_count": self.failed_sessions_count,
            "completed_sessions": self.completed_sessions,
            "sessions_last_24h": self.sessions_last_24h,
            "cost_last_24h": round(self.cost_last_24h, 4),
            "total_tool_calls": self.total_tool_calls,
            "total_api_calls": self.total_api_calls,
            "total_cost": round(self.total_cost, 4),
            "total_estimated_tokens": self.total_estimated_tokens,
            "total_cache_hits": self.total_cache_hits,
            "total_subagents": self.total_subagents,
            "total_write_edits": self.total_write_edits,
            "avg_duration_s": round(self.avg_duration_s, 1),
            "status_counts": dict(self.status_counts),
            "provider_totals": dict(self.provider_totals),
            "model_totals": dict(self.model_totals),
            "tool_totals": dict(self.tool_totals),
            "longest_sessions": [s.to_dict() for s in self.longest_sessions[:8]],
            "recent_sessions": [s.to_dict() for s in self.recent_sessions[:8]],
            "highest_cost_sessions": [s.to_dict() for s in self.highest_cost_sessions[:8]],
            "attention_sessions": [s.to_dict() for s in self.attention_sessions[:8]],
        }


def build_dashboard_summary(*, limit: int = 200) -> DashboardSummary:
    sessions = list_session_stats(limit=limit)
    summary = DashboardSummary(user=build_user_profile(), session_count=len(sessions))
    now = time.time()
    day_ago = now - 86_400
    duration_sum = 0.0

    for s in sessions:
        summary.total_tool_calls += s.tool_calls
        summary.total_api_calls += s.api_calls
        summary.total_cost += s.cost
        summary.total_estimated_tokens += s.estimated_tokens
        summary.total_cache_hits += s.cache_hit_tokens
        summary.total_subagents += s.subagent_runs
        summary.total_write_edits += s.write_edits
        duration_sum += s.duration_s

        if s.is_active:
            summary.active_sessions += 1
        status = (s.exit_status or "in progress").strip() or "in progress"
        summary.status_counts[status] = summary.status_counts.get(status, 0) + 1
        if s.is_failed:
            summary.failed_sessions_count += 1
        if status == "Submitted":
            summary.completed_sessions += 1

        if s.updated_at >= day_ago:
            summary.sessions_last_24h += 1
            summary.cost_last_24h += s.cost

        if s.provider:
            key = f"{s.provider}/{s.model}" if s.model else s.provider
            summary.provider_totals[s.provider] = summary.provider_totals.get(s.provider, 0) + 1
            summary.model_totals[key] = summary.model_totals.get(key, 0) + 1

        for tool, count in s.tool_counts.items():
            summary.tool_totals[tool] = summary.tool_totals.get(tool, 0) + count

    if sessions:
        summary.avg_duration_s = duration_sum / len(sessions)

    summary.longest_sessions = sorted(sessions, key=lambda x: x.duration_s, reverse=True)[:8]
    summary.recent_sessions = sorted(sessions, key=lambda x: x.updated_at, reverse=True)[:8]
    summary.highest_cost_sessions = sorted(sessions, key=lambda x: x.cost, reverse=True)[:8]
    summary.attention_sessions = sorted(
        [s for s in sessions if s.is_failed or s.is_active or s.tool_failures > 0],
        key=lambda x: x.updated_at,
        reverse=True,
    )[:8]
    return summary
