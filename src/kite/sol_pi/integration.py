"""Wire SoL-Pi mechanisms into the Kite harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from kite.agent.hooks import HookBus
from kite.sol_pi import action_fusion, evidence, observation_core, plan
from kite.sol_pi.config import SolPiConfig, load_sol_pi_config
from kite.sol_pi.economics import decide_compaction
from kite.tools import Tool

FORCE_COMPACT_KEY = "sol_pi_force_compact"
RECALL_MAX_BYTES = 16 * 1024
RECALL_MAX_LINES = 400


@dataclass
class SolPiSession:
    config: SolPiConfig
    runtime_root: Path
    sent_counts: dict[str, int] = field(default_factory=dict)
    observations: dict[str, observation_core.Observation] = field(default_factory=dict)
    plan_steps: tuple[plan.PlanStep, ...] = ()
    boundary_request_counts: list[int] = field(default_factory=list)
    requests_since_boundary: int = 0
    prior_compaction_count: int = 0
    carried_debt_tokens: int = 0
    context_samples: list[int] = field(default_factory=list)
    last_context_tokens: int = 0
    reducer_call: Callable[[str, str, bool, evidence.ArchiveObject], str] | None = None


def runtime_root_for_session(session_id: str, cwd: str) -> Path:
    base = Path(cwd).expanduser().resolve() / ".kite" / "sol-pi" / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def attach_sol_pi(harness: Any, cwd: str = ".") -> SolPiSession | None:
    """Load config, register hooks, and stash session state on the harness."""
    try:
        config = load_sol_pi_config(cwd)
    except ValueError as exc:
        raise
    if not config.enabled:
        harness.sol_pi = None
        return None

    session = SolPiSession(config=config, runtime_root=Path(cwd))
    harness.sol_pi = session
    hooks: HookBus = harness.hooks
    hooks.context["sol_pi_session"] = session

    if config.observation_pack:
        hooks.on("before_query", lambda messages, **_: _project_observations(session, messages))

    if config.evidence_preserving_reducer or config.observation_pack:
        hooks.on("after_tool", _make_after_tool(session))

    if config.online_context_compact:
        hooks.on("before_compact", lambda messages, **_: _before_compact(session, messages, hooks))

    return session


def apply_sol_pi_tools(tools: list[Tool], session: SolPiSession | None, *, bash_fn: Callable[[dict], dict]) -> list[Tool]:
    if session is None or not session.config.enabled:
        return tools

    out: list[Tool] = []
    for tool in tools:
        if session.config.action_fusion and tool.name in {"edit", "write"}:
            out.append(_wrap_fusion_tool(tool, bash_fn))
        else:
            out.append(tool)

    if session.config.observation_pack:
        out.append(_obs_recall_tool(session))
    return out


def bind_sol_pi_session(session: SolPiSession, *, session_id: str, cwd: str) -> None:
    session.runtime_root = runtime_root_for_session(session_id, cwd)


def _make_after_tool(session: SolPiSession):
    def after_tool(out: dict, *, tool: str, args: dict, **_: Any) -> dict | None:
        if session.config.online_context_compact and tool == "todo_write" and out.get("items"):
            _on_plan_update(session, out.get("items"))
        if not out.get("ok") or out.get("blocked"):
            return out
        body = str(out.get("output") or out.get("error") or "")
        if session.config.evidence_preserving_reducer and tool == "bash":
            out = _maybe_reduce_bash(session, out, args, body) or out
            body = str(out.get("output") or "")
        if session.config.observation_pack and body:
            tool_call_id = str(args.get("_tool_call_id") or tool)
            obs = observation_core.create_observation(tool, tool_call_id, body, session.runtime_root)
            if obs is not None:
                observation_core.ensure_stored(obs)
                session.observations[obs.id] = obs
        return out

    return after_tool


def _maybe_reduce_bash(session: SolPiSession, out: dict, args: dict, body: str) -> dict | None:
    command = str(args.get("command") or "")
    if not evidence.is_diagnostic_command(command):
        return None
    encoded = body.encode("utf-8")
    if len(encoded) < evidence.DEFAULT_MIN_BYTES:
        return None
    if evidence.LIKELY_SECRET.search(body):
        return None
    archive = evidence.ArchiveObject(
        hash=evidence.sha256_text(body),
        bytes=len(encoded),
        lines=observation_core.count_lines(body),
        body=body,
    )
    if session.reducer_call is None:
        return None
    is_error = not bool(out.get("ok", True)) or int(out.get("returncode") or 0) != 0
    try:
        raw = session.reducer_call(command, body, is_error, archive)
    except Exception:
        return None
    validated, reason = evidence.validate_receipt(raw, archive, body, is_error)
    if validated is None:
        return None
    receipt_body = evidence.receipt_text(validated, archive, command)
    if len(receipt_body.encode("utf-8")) >= len(encoded):
        return None
    return {**out, "output": receipt_body, "sol_pi_reduced": True}


def _on_plan_update(session: SolPiSession, items: Any) -> None:
    next_steps = plan.parse_todo_items(items)
    if next_steps is None:
        return
    transition = plan.analyze_plan_transition(session.plan_steps, next_steps)
    session.plan_steps = next_steps
    if transition.completed_steps:
        session.boundary_request_counts.append(session.requests_since_boundary)
        session.requests_since_boundary = 0


def _before_compact(session: SolPiSession, messages: list[dict], hooks: HookBus) -> list[dict]:
    from kite.context.window import estimate_usage

    usage = estimate_usage(system="", messages=messages, tool_tokens=0, window=200_000)
    session.last_context_tokens = usage.total_tokens
    session.context_samples.append(usage.total_tokens)
    if len(session.context_samples) > 1:
        session.requests_since_boundary += 1

    remaining = sum(1 for s in session.plan_steps if s.status != "completed")
    avg_inc = None
    if len(session.context_samples) >= 2:
        deltas = [
            b - a for a, b in zip(session.context_samples, session.context_samples[1:], strict=False)
        ]
        avg_inc = sum(deltas) / len(deltas) if deltas else None

    decision = decide_compaction(
        write_tokens=usage.total_tokens,
        archive_tokens=int(usage.total_tokens * 0.75),
        memo_tokens=int(usage.total_tokens * 0.35),
        context_tokens=usage.total_tokens,
        completed_boundary_request_counts=tuple(session.boundary_request_counts) or None,
        remaining_boundaries=max(remaining, 1),
        average_context_token_increment=avg_inc,
        context_window_tokens=usage.window,
        prior_compaction_count=session.prior_compaction_count,
        carried_debt_tokens=session.carried_debt_tokens,
        cache_debt_repayment_tokens=0,
        cache_write_read_ratio=session.config.cache_write_read_ratio,
    )
    if decision.compact:
        hooks.context[FORCE_COMPACT_KEY] = True
    return messages


def _project_observations(session: SolPiSession, messages: list[dict]) -> list[dict]:
    projected: list[dict] = []
    for message in messages:
        if message.get("role") != "tool":
            projected.append(message)
            continue
        content = str(message.get("content") or "")
        extra = message.get("extra") or {}
        raw = extra.get("raw") or {}
        tool_name = str((raw.get("metadata") or {}).get("tool") or extra.get("tool") or "tool")
        obs = _observation_for_content(session, tool_name, content, message)
        if obs is None:
            projected.append(message)
            continue
        count = session.sent_counts.get(obs.id, 0) + 1
        session.sent_counts[obs.id] = count
        if count <= observation_core.FULL_SENDS:
            projected.append(message)
        else:
            projected.append({**message, "content": observation_core.placeholder_for(obs)})
    return projected


def _observation_for_content(
    session: SolPiSession,
    tool_name: str,
    content: str,
    message: dict,
) -> observation_core.Observation | None:
    for obs in session.observations.values():
        if obs.text == content:
            return obs
    tool_call_id = str(message.get("tool_call_id") or tool_name)
    return observation_core.create_observation(tool_name, tool_call_id, content, session.runtime_root)


def _wrap_fusion_tool(tool: Tool, bash_fn: Callable[[dict], dict]) -> Tool:
    params = dict(tool.parameters)
    props = dict(params.get("properties") or {})
    props["then_run"] = {
        **action_fusion.THEN_RUN_SCHEMA,
        "description": "Optional command to run on this file after a successful mutation",
    }
    params["properties"] = props

    def execute_fn(args: dict[str, Any]) -> dict[str, Any]:
        then_run = args.pop("then_run", None)
        path_str = str(args.get("path") or "")
        path = Path(path_str).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()

        def mutate() -> dict[str, Any]:
            return tool.run(args)

        return action_fusion.run_mutation_then_run(path, then_run, mutate, bash_fn)

    return Tool(
        name=tool.name,
        description=tool.description + " Supports optional then_run to fuse a follow-up shell command.",
        parameters=params,
        execute_fn=execute_fn,
    )


def _obs_recall_tool(session: SolPiSession) -> Tool:
    def execute_fn(args: dict[str, Any]) -> dict[str, Any]:
        obs_id = str(args.get("id") or "")
        if not observation_core.is_observation_id(obs_id):
            return {"ok": False, "error": f"Unknown observation id: {obs_id}", "output": f"Unknown observation id: {obs_id}"}
        offset = int(args.get("offset") or 0)
        obs = session.observations.get(obs_id)
        path = obs.file_path if obs else observation_core.observation_path(session.runtime_root, obs_id)
        if not path.is_file():
            return {"ok": False, "error": f"Unknown observation id: {obs_id}", "output": f"Unknown observation id: {obs_id}"}
        chunk = observation_core.read_recall_chunk(
            path,
            offset,
            max_bytes=RECALL_MAX_BYTES - 512,
            max_lines=RECALL_MAX_LINES - 2,
        )
        header = (
            f"[obs_recall id={obs_id} offset={offset} next_offset={chunk.next_offset} eof={chunk.eof}]\n"
            f"[chunk_bytes={chunk.bytes} chunk_lines={chunk.lines}; use next_offset to continue]"
        )
        return {"ok": True, "output": f"{header}\n{chunk.text}"}

    return Tool(
        name="obs_recall",
        description="Read a stored large tool result by observation id and byte offset.",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
            },
            "required": ["id"],
        },
        execute_fn=execute_fn,
    )


def note_compaction_completed(session: SolPiSession | None, *, before_tokens: int, after_tokens: int) -> None:
    if session is None:
        return
    session.prior_compaction_count += 1
    debt = max(0, before_tokens - after_tokens)
    session.carried_debt_tokens = max(0, session.carried_debt_tokens + debt // 4)
