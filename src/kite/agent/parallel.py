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


def _crew_scalar(value: Any) -> str:
    return str(value or "").strip()


def _crew_sync_eligible(args: dict[str, Any]) -> bool:
    """A lone sync `subagent` call that may join a coalesced crew."""
    if args.get("wait_for") or args.get("job_ids"):
        return False  # collect calls stay separate
    if args.get("prompts") or args.get("tasks"):
        return False  # already a crew
    if args.get("background") is True:
        return False  # async semantics differ
    if "wait" in args and args.get("wait") is False:
        return False
    # Plural crew keys need positional alignment the merger cannot infer.
    for key in ("labels", "profiles", "roles", "providers", "models", "contexts", "scopes", "timeouts"):
        if args.get(key):
            return False
    return bool(_crew_scalar(args.get("prompt")))


def _crew_compatible(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Same dispatch semantics: retry/abort/parent/run/timeout-shape must match."""
    if bool(first.get("retryable", True)) != bool(second.get("retryable", True)):
        return False
    if bool(first.get("abort_on_failure", False)) != bool(second.get("abort_on_failure", False)):
        return False
    for key in ("parent_id", "run_id", "parent_run_id", "provider", "model", "profile", "role"):
        if _crew_scalar(first.get(key)) != _crew_scalar(second.get(key)):
            # Scalars that differ per call are preserved positionally below,
            # except identity keys that would split the crew's run scope.
            if key in ("parent_id", "run_id", "parent_run_id"):
                return False
    return True


_CREW_POSITIONAL = (
    ("labels", "label"),
    ("profiles", "profile"),
    ("roles", "role"),
    ("providers", "provider"),
    ("models", "model"),
    ("contexts", "context"),
    ("timeouts", "timeout_s"),
)


def _merge_crew_calls(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine sibling sync subagent calls into one `prompts` crew dispatch."""
    first_args = group[0].get("arguments") if isinstance(group[0].get("arguments"), dict) else {}
    merged_args: dict[str, Any] = {"prompts": [_crew_scalar(a.get("arguments", {}).get("prompt")) for a in group]}
    member_args = [
        a.get("arguments") if isinstance(a.get("arguments"), dict) else {} for a in group
    ]
    for plural, singular in _CREW_POSITIONAL:
        values = [_crew_scalar(m.get(singular)) for m in member_args]
        if any(values):
            merged_args[plural] = values
    scopes = [m.get("scope") for m in member_args]
    if any(s for s in scopes if s):
        merged_args["scopes"] = scopes
    if any(bool(m.get("abort_on_failure", False)) for m in member_args):
        merged_args["abort_on_failure"] = True
    if not bool(first_args.get("retryable", True)):
        merged_args["retryable"] = False
    for key in ("parent_id", "run_id", "parent_run_id"):
        value = _crew_scalar(first_args.get(key))
        if value:
            merged_args[key] = value
    merged = dict(group[0])
    merged["arguments"] = merged_args
    return merged


def coalesce_crew_calls(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive sync `subagent` calls into one parallel crew dispatch.

    Sibling workers are independent by construction (workers cannot nest, each
    gets fresh context), so one crew of N beats N serial run_one round-trips
    with identical semantics. Interrupt granularity coarsens from per-call to
    per-crew — the crew still honors per-worker cancel/timeout.
    """
    if len(actions) < 2:
        return list(actions)
    merged: list[dict[str, Any]] = []
    i = 0
    while i < len(actions):
        action = actions[i]
        args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        if str(action.get("tool") or "") == "subagent" and _crew_sync_eligible(args):
            group = [action]
            j = i + 1
            while j < len(actions):
                nxt = actions[j]
                nargs = nxt.get("arguments") if isinstance(nxt.get("arguments"), dict) else {}
                if (
                    str(nxt.get("tool") or "") == "subagent"
                    and _crew_sync_eligible(nargs)
                    and _crew_compatible(args, nargs)
                ):
                    group.append(nxt)
                    j += 1
                else:
                    break
            if len(group) > 1:
                merged.append(_merge_crew_calls(group))
                i = j
                continue
        merged.append(action)
        i += 1
    return merged


def plan_execution_batches(actions: list[dict[str, Any]], *, cwd: str) -> list[list[dict[str, Any]]]:
    """Partition model tool calls into sequential batches; each batch may run in parallel."""
    actions = coalesce_crew_calls(actions)
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
    "coalesce_crew_calls",
    "is_parallel_safe",
    "paths_overlap",
    "plan_execution_batches",
]
