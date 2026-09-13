"""Parallel tool batching — disjoint paths run concurrently (reads + writes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kite.tools.metadata import is_concurrency_safe

# Never run alongside other tools in one thread pool.
_SERIAL_ONLY = frozenset({"bash", "todo_write", "task", "subagent", "submit", "memory", "set_cwd", "skill"})

_PATH_ARG_TOOLS = frozenset({"read", "write", "edit", "grep", "glob", "ls"})
_WRITE_TOOLS = frozenset({"write", "edit"})


def _norm_posix(path: str, cwd: str) -> str:
    raw = (path or ".").strip()
    if not raw:
        raw = "."
    p = Path(raw)
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        return p.resolve().as_posix()
    except OSError:
        return p.as_posix()


def paths_overlap(left: str, right: str) -> bool:
    """True when two workspace paths could observe the same file tree."""
    a = left.rstrip("/")
    b = right.rstrip("/")
    if not a or not b:
        return True
    if a == b:
        return True
    return a.startswith(b + "/") or b.startswith(a + "/")


def action_paths(tool: str, args: dict[str, Any], *, cwd: str) -> frozenset[str]:
    """Best-effort paths touched or read by one tool call."""
    if tool not in _PATH_ARG_TOOLS:
        return frozenset()
    raw = str(args.get("path") or args.get("file_path") or args.get("root") or ".")
    return frozenset({_norm_posix(raw, cwd)})


def is_parallel_safe(tool: str) -> bool:
    """Static parallel safety (read-only / network reads)."""
    return is_concurrency_safe(tool)


def action_parallel_eligible(tool: str) -> bool:
    """True when this tool may join a parallel batch (possibly with path checks)."""
    if tool in _SERIAL_ONLY:
        return False
    if is_concurrency_safe(tool):
        return True
    return tool in _WRITE_TOOLS


def actions_conflict(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    cwd: str,
) -> bool:
    """True when two actions must not run concurrently."""
    lt = str(left.get("tool") or "")
    rt = str(right.get("tool") or "")
    if lt in _SERIAL_ONLY or rt in _SERIAL_ONLY:
        return True
    if not action_parallel_eligible(lt) or not action_parallel_eligible(rt):
        return True
    largs = left.get("arguments") if isinstance(left.get("arguments"), dict) else {}
    rargs = right.get("arguments") if isinstance(right.get("arguments"), dict) else {}
    lpaths = action_paths(lt, largs, cwd=cwd)
    rpaths = action_paths(rt, rargs, cwd=cwd)
    if not lpaths or not rpaths:
        return lt in _WRITE_TOOLS or rt in _WRITE_TOOLS
    for lp in lpaths:
        for rp in rpaths:
            if paths_overlap(lp, rp) and (lt in _WRITE_TOOLS or rt in _WRITE_TOOLS):
                return True
    return False


def can_parallelize_batch(actions: list[dict[str, Any]], *, cwd: str) -> bool:
    """True when every action in the batch can run concurrently."""
    if len(actions) <= 1:
        return False
    tools = [str(a.get("tool") or "") for a in actions]
    if any(t in _SERIAL_ONLY for t in tools):
        return False
    if not all(action_parallel_eligible(t) for t in tools):
        return False
    for i, left in enumerate(actions):
        for right in actions[i + 1 :]:
            if actions_conflict(left, right, cwd=cwd):
                return False
    return True


def plan_execution_batches(actions: list[dict[str, Any]], *, cwd: str) -> list[list[dict[str, Any]]]:
    """Partition model tool calls into sequential batches; each batch may run in parallel."""
    if len(actions) <= 1:
        return [list(actions)]

    remaining = list(actions)
    batches: list[list[dict[str, Any]]] = []

    while remaining:
        batch = [remaining.pop(0)]
        tool = str(batch[0].get("tool") or "")
        if tool in _SERIAL_ONLY or not action_parallel_eligible(tool):
            batches.append(batch)
            continue
        while remaining and can_parallelize_batch(batch + [remaining[0]], cwd=cwd):
            batch.append(remaining.pop(0))
        batches.append(batch)

    return batches


__all__ = [
    "action_paths",
    "action_parallel_eligible",
    "actions_conflict",
    "can_parallelize_batch",
    "is_parallel_safe",
    "paths_overlap",
    "plan_execution_batches",
]
