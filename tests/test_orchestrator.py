"""Subagent orchestrator — dispatch, success semantics, parallel fan-out."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from kite.agent.cancel import CancelToken
from kite.agent.orchestrator import (
    SubagentOrchestrator,
    evaluate_subagent_result,
    gate_result,
    summarize_result,
    worker_glyph,
)


def test_result_semantics_glyph_rubric_and_clamp() -> None:
    assert worker_glyph(1) == "◆"
    assert worker_glyph(2) == "●"
    assert worker_glyph(7) == worker_glyph(1)

    ok, quality, summary = evaluate_subagent_result(
        {"exit_status": "Submitted", "submission": "all good"}
    )
    assert ok is True
    assert quality == "done"
    assert summary == "all good"

    text = "x" * 50
    ok, quality, _ = evaluate_subagent_result({"exit_status": "LimitsExceeded", "submission": text})
    assert ok is True
    assert quality == "partial"

    ok, quality, _ = evaluate_subagent_result({"exit_status": "Error", "error": "boom"})
    assert ok is False
    assert quality == "failed"

    ok, quality, _ = evaluate_subagent_result({"exit_status": "LimitsExceeded", "submission": ""})
    assert (ok, quality) == (False, "failed")
    ok, quality, _ = evaluate_subagent_result({"exit_status": "Stalled", "submission": "some notes"})
    assert (ok, quality) == (True, "partial")
    full = "## Result\nok\n## Files touched\n- a.py\n## Tests\nnone"
    ok, quality, _ = evaluate_subagent_result({"exit_status": "Stalled", "submission": full})
    assert (ok, quality) == (True, "done")
    ok, quality, summary = evaluate_subagent_result({"exit_status": "Submitted", "submission": "all good"})
    assert (ok, quality, summary) == (True, "done", "all good")

    clamped = summarize_result("A" * 5000)
    assert len(clamped) <= 2000
    assert "truncated" in clamped
    assert clamped.startswith("A" * 100) and clamped.endswith("A" * 100)
    assert summarize_result("short") == "short"


def test_run_one_events_view_and_thread_labels() -> None:
    events: list[tuple[str, dict]] = []

    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": f"done: {prompt[:20]}"}

    orch = SubagentOrchestrator(
        runner=runner,
        on_event=lambda e: events.append((e.kind, dict(e.payload))),
        timeout_seconds=0,
    )
    out = orch.run_one("explore auth module", label="scout")
    assert out["ok"] is True
    assert out["quality"] == "done"
    kinds = [k for k, _ in events]
    assert "subagent_start" in kinds
    assert "subagent_end" in kinds
    assert orch.manager_view()[-1]["label"] == "scout"
    assert orch.manager_view()[-1]["glyph"]

    by_kind = {k: p for k, p in events if k in {"subagent_start", "subagent_end"}}
    assert by_kind["subagent_start"]["label"] == "scout"
    assert "scout" in by_kind["subagent_start"]["thread"]
    assert by_kind["subagent_end"]["label"] == "scout"
    assert "scout" in by_kind["subagent_end"]["thread"]


def test_run_parallel_orders_counts_and_input_order() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        if "fail" in prompt:
            return {"exit_status": "Error", "error": "nope"}
        return {"exit_status": "Submitted", "submission": prompt}

    events: list[str] = []
    orch = SubagentOrchestrator(
        runner=runner,
        on_event=lambda e: events.append(e.kind),
        max_workers=2,
        timeout_seconds=0,
    )
    out = orch.run_parallel(
        ["scan a", "scan fail", "scan b"],
        labels=["alpha", "broken", "beta"],
    )
    assert out["succeeded"] == 2
    assert out["ok"] is False
    assert "crew report" in out["output"]
    assert "succeeded" in out["output"]
    assert "alpha" in out["output"]
    assert "orchestrator_start" in events
    assert "orchestrator_end" in events

    def ordered_runner(prompt: str, *, cancel: CancelToken | None = None, **_: object) -> dict:
        if "slow" in prompt:
            time.sleep(0.25)
        return {"exit_status": "Submitted", "submission": f"out:{prompt}"}

    orch2 = SubagentOrchestrator(runner=ordered_runner, max_workers=2, timeout_seconds=0)
    ordered = orch2.run_parallel(["slow first", "fast second"], labels=["alpha", "beta"])
    outputs = [str(r.get("output") or "") for r in ordered["results"]]
    assert outputs[0].startswith("out:slow first")
    assert outputs[1].startswith("out:fast second")
    assert ordered["output"].index("alpha") < ordered["output"].index("beta")


def test_worker_cost_propagates_to_tree_total() -> None:
    def paid_runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": f"done:{prompt}", "cost": 0.02}

    orch = SubagentOrchestrator(runner=paid_runner, max_workers=2, timeout_seconds=0)
    one = orch.run_one("solo task", label="solo")
    assert one["ok"] is True and one["cost"] == 0.02
    crew = orch.run_parallel(["a", "b"], labels=["w1", "w2"])
    assert crew["total_cost"] == pytest.approx(0.04)
    assert all(r.get("cost") == 0.02 for r in crew["results"])

    long_text = "B" * 5000
    assert "[truncated" in summarize_result(long_text) and len(summarize_result(long_text)) <= 1600


def test_dispatch_validation_async_depth_and_combos() -> None:
    orch = SubagentOrchestrator(runner=MagicMock())
    out = orch.dispatch({})
    assert out["ok"] is False

    out = orch.dispatch({"wait_for": ["abc"], "prompt": "also run this"})
    assert out["ok"] is False
    assert "cannot be combined" in out["output"]

    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": "ok"}

    auto = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    autoed = auto.dispatch(
        {"prompt": "Run a read-only survey in the background while I continue refactoring."}
    )
    assert autoed.get("background") is True
    assert autoed.get("dispatch_reason") == "auto-async"
    assert "dispatch_hint" in autoed

    gated = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    blocked = gated.dispatch({"prompt": "nested work"}, depth=1)
    assert blocked["ok"] is False
    assert "nested" in str(blocked.get("error") or "")
    assert gated.spawn_count == 0  # blocked dispatches consume no budget

    allowed = gated.dispatch({"prompt": "nested work"}, depth=1, allow_nested=True)
    assert allowed["ok"] is True
    assert gated.spawn_count == 1

    top = gated.dispatch({"prompt": "top-level work"})
    assert top["ok"] is True

    nested_orch = SubagentOrchestrator(runner=runner, timeout_seconds=0, depth=1)
    assert nested_orch.dispatch({"prompt": "x"})["ok"] is False
    assert nested_orch.dispatch({"prompt": "x"}, allow_nested=True)["ok"] is True


def test_kill_cancels_running_tasks() -> None:
    from kite.agent.orchestrator import SubagentTask

    token = CancelToken()
    orch = SubagentOrchestrator(runner=MagicMock(), timeout_seconds=0)
    orch.tasks.append(
        SubagentTask(id="abc12345", prompt="p", label="worker", status="running", cancel=token)
    )
    assert orch.kill("abc12345") is True
    assert token.is_set()

    token_a = CancelToken()
    token_b = CancelToken()
    orch.tasks.extend(
        [
            SubagentTask(id="a1", prompt="p", label="w1", status="running", cancel=token_a),
            SubagentTask(id="b2", prompt="p", label="w2", status="running", cancel=token_b),
            SubagentTask(id="c3", prompt="p", label="w3", status="finished", cancel=CancelToken()),
        ]
    )
    assert orch.kill_all() == 2
    assert token_a.is_set()
    assert token_b.is_set()


def test_background_spawn_and_collect() -> None:
    def slow_runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        time.sleep(0.3)
        return {"exit_status": "Submitted", "submission": "late"}

    orch = SubagentOrchestrator(runner=slow_runner, timeout_seconds=0)
    started = time.monotonic()
    out = orch.run_one_background("explore", label="scout")
    elapsed = time.monotonic() - started
    assert elapsed < 0.15
    assert out["background"] is True
    assert out["job_id"]
    assert out["dispatch"] == "async"

    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        time.sleep(0.05)
        return {"exit_status": "Submitted", "submission": f"findings: {prompt}"}

    orch2 = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    spawned = orch2.run_one_background("auth paths", label="scout")
    job_id = str(spawned["job_id"])
    collected = orch2.wait_for([job_id], timeout_seconds=5)
    assert job_id not in collected.get("pending", [])
    assert "findings" in collected["output"]
    assert collected["results"][job_id]["ok"] is True


def test_prune_and_context_compose() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": "ok"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0, max_spawns=200)
    for i in range(80):
        orch.run_one(f"p{i}", label=f"w{i}")
    assert len(orch.tasks) <= 64

    from kite.agent.subagent_profiles import SubagentProfile

    prof = SubagentProfile(id="scout", label="Scout", role="architect", prompt="Survey only.", bundled=True)
    composed = prof.compose("map auth", project_root="/repo", execution_cwd="/repo/sub", context="focus on login")
    assert "## Context packet" in composed
    assert "/repo" in composed and "focus on login" in composed
    assert "## Summary contract" in composed and "## Files touched" in composed
    # persona first, packet before task, contract last
    assert composed.index("# Subagent") < composed.index("## Context packet") < composed.index("## Task")
    assert composed.index("## Task") < composed.index("## Summary contract")
    # backward compatible: old single-arg call still works
    legacy = prof.compose("map auth")
    assert "map auth" in legacy and "## Summary contract" in legacy
    # context capped at 2000 chars
    capped = prof.compose("t", context="y" * 5000)
    assert len(capped) < len("y" * 5000)


def test_revise_and_scope_gate() -> None:
    calls: list[str] = []

    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        calls.append(prompt)
        if len(calls) == 1:
            return {"exit_status": "Submitted", "submission": "done", "files_touched": ["etc/passwd"]}
        return {"exit_status": "Submitted", "submission": "fixed", "files_touched": ["src/kite/a.py"]}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    out = orch.run_one("edit the module", label="w", scope=["src/kite"])
    assert len(calls) == 2 and "## Revise" in calls[1]
    assert out["ok"] is True and out["quality"] == "done"

    from kite.agent.orchestrator import SubagentTask

    task = SubagentTask(id="t1", prompt="p", label="w", scope=["src/kite"])
    blocked = gate_result(task, {"exit_status": "Submitted", "files_touched": ["src/kite/a.py", "etc/passwd"]})
    assert "out-of-scope" in blocked and "etc/passwd" in blocked
    assert gate_result(task, {"exit_status": "Submitted", "files_touched": ["src/kite/a.py"]}) == ""
    assert gate_result(SubagentTask(id="t2", prompt="p", label="w"), {"files_touched": ["anywhere"]}) == ""


def test_retry_policy_single_and_disabled() -> None:
    calls: list[str] = []

    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        calls.append(prompt)
        return {"exit_status": "Error", "error": "boom"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    out = orch.run_one("do the thing", label="w")
    assert out["quality"] == "failed"
    assert len(calls) == 2
    assert "## Revise (retry 1/1)" in calls[1]
    assert orch.tasks[-1].retried is True

    fresh: list[str] = []
    orch2 = SubagentOrchestrator(
        runner=lambda prompt, *, cancel=None: (fresh.append(prompt), {"exit_status": "Error", "error": "boom"})[1],
        timeout_seconds=0,
    )
    orch2.run_one("do the thing", label="w", retryable=False)
    assert len(fresh) == 1


def test_registry_tracks_parent_children() -> None:
    from kite.agent.orchestrator import clear_registry, list_children

    clear_registry()
    try:

        def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
            return {"exit_status": "Submitted", "submission": f"done: {prompt}"}

        orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
        out = orch.dispatch({"prompts": ["a", "b"], "labels": ["one", "two"], "parent_id": "p1"})
        assert out["ok"] is True
        kids = list_children("p1")
        assert len(kids) == 2
        assert {t.label for t in kids} == {"one", "two"}
        assert all(t.parent_id == "p1" and t.run_id for t in kids)
        assert out.get("run_id") == kids[0].run_id == kids[1].run_id
    finally:
        clear_registry()


def test_abort_and_sibling_results() -> None:
    saw_cancel = False

    def runner(prompt: str, *, cancel: CancelToken | None = None, **_: object) -> dict:
        nonlocal saw_cancel
        if "fail" in prompt:
            return {"exit_status": "Error", "error": "boom"}
        for _ in range(100):
            if cancel is not None and cancel.is_set():
                saw_cancel = True
                return {"exit_status": "Interrupted", "submission": ""}
            time.sleep(0.02)
        return {"exit_status": "Submitted", "submission": f"done: {prompt}"}

    orch = SubagentOrchestrator(runner=runner, max_workers=2, timeout_seconds=0)
    out = orch.run_parallel(["do fail now", "slow sibling"], labels=["bad", "slow"], abort_on_failure=True)
    assert out["ok"] is False
    assert saw_cancel is True
    slow_result = out["results"][1]
    assert slow_result["ok"] is False

    def kind_runner(prompt: str, *, cancel: CancelToken | None = None, **_: object) -> dict:
        if "fail" in prompt:
            return {"exit_status": "Error", "error": "boom"}
        return {"exit_status": "Submitted", "submission": f"done: {prompt}"}

    orch2 = SubagentOrchestrator(runner=kind_runner, max_workers=2, timeout_seconds=0)
    kept = orch2.run_parallel(["do fail now", "fine sibling"], labels=["bad", "good"])
    assert kept["ok"] is False
    assert kept["results"][1]["ok"] is True


def test_per_worker_timeout_marks_failed() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None, **_: object) -> dict:
        time.sleep(0.5)
        return {"exit_status": "Submitted", "submission": "too late"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    out = orch.run_one("slow job", label="turtle", timeout_s=0.15)
    assert out["ok"] is False
    assert out.get("quality") == "failed"
    assert "timed out after 0.15s" in str(out.get("output") or "")
    assert orch.tasks[-1].quality == "failed"


def test_profiles_tiers_scopes_and_allowlist() -> None:
    from kite.agent.subagent_profiles import (
        ROLE_MODEL_TIERS,
        get_profile,
        resolve_worker_model,
        worker_tool_allowlist,
    )

    assert get_profile("scout").model_role == "fast"
    assert get_profile("reviewer").model_role == "smart"
    assert get_profile("context").model_role == "smart"  # architect role ~ planner tier
    assert get_profile("coder").model_role == "coder"
    assert get_profile("shell").model_role == "coder"
    assert get_profile("scout").tools == ("read", "grep", "glob", "ls")
    assert get_profile("reviewer").tools == ("read", "grep", "glob", "ls")
    assert get_profile("shell").tools == ("read", "bash", "grep", "glob", "ls")
    assert get_profile("coder").tools == ("read", "write", "edit", "bash", "grep", "glob", "ls", "todo_write", "todo_read", "task")
    assert get_profile("context").tools == ("read", "grep", "glob", "ls", "task")

    assert set(ROLE_MODEL_TIERS) == {"fast", "coder", "smart"}
    assert all(chain[0] == "parent" for chain in ROLE_MODEL_TIERS.values())
    # explicit model= wins over every tier
    assert resolve_worker_model(explicit_model="m-explicit", parent_model="m-parent", model_role="fast") == "m-explicit"
    # tier preference: parent first, then runtime default ("")
    assert resolve_worker_model(parent_model="m-parent", model_role="smart") == "m-parent"
    assert resolve_worker_model(model_role="coder") == ""
    assert resolve_worker_model(parent_model="m-parent", model_role="bogus") == "m-parent"

    from kite.agent.subagent_profiles import SubagentProfile

    scoped = SubagentProfile(id="s", label="S", tools=("read", "subagent", "memory", "bash"))
    assert worker_tool_allowlist(scoped) == ["read", "bash"]  # nesting/memory stripped
    assert worker_tool_allowlist(SubagentProfile(id="c", label="C")) is None  # empty = inherit
    assert worker_tool_allowlist(None) is None


def test_profile_file_scope_parsing(tmp_path) -> None:
    from kite.agent.subagent_profiles import _parse_profile_file

    messy = tmp_path / "messy.md"
    messy.write_text(
        "---\nid: messy\nlabel: Messy\nrole: debugger\ntools: Read, BASH, subagent, !!, read\n"
        "model_role: ultra\n---\n\nDo things.\n",
        encoding="utf-8",
    )
    prof = _parse_profile_file(messy, "messy", bundled=False)
    assert prof is not None
    assert prof.tools == ("read", "bash", "subagent")  # lowered, deduped, garbage dropped
    assert prof.model_role == "coder"  # bogus tier falls back to worker default

    inherit = tmp_path / "plain.md"
    inherit.write_text("---\nid: plain\nlabel: Plain\ntools:\n---\n\nBody.\n", encoding="utf-8")
    plain = _parse_profile_file(inherit, "plain", bundled=False)
    assert plain is not None and plain.tools == ()


def test_spawn_budget_exceeded_errors() -> None:
    def runner(prompt: str, *, cancel: CancelToken | None = None) -> dict:
        return {"exit_status": "Submitted", "submission": "ok"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0, max_spawns=2)
    assert orch.run_one("one", label="a")["ok"] is True
    assert orch.run_one("two", label="b")["ok"] is True
    assert orch.spawn_count == 2
    third = orch.run_one("three", label="c")
    assert third["ok"] is False
    assert "budget" in str(third.get("error") or "")
    assert orch.spawn_count == 2  # failed reservation consumes nothing

    crew = orch.run_parallel(["x", "y"], labels=["x", "y"])
    assert crew["ok"] is False
    assert "budget" in str(crew.get("error") or "")

    bg = orch.run_one_background("z", label="z")
    assert bg["ok"] is False
    assert "budget" in str(bg.get("error") or "")


def test_dispatch_forwards_profile_allowlist() -> None:
    seen: list[dict] = []

    def runner(prompt: str, **kwargs: object) -> dict:
        seen.append(dict(kwargs))
        return {"exit_status": "Submitted", "submission": "ok"}

    orch = SubagentOrchestrator(runner=runner, timeout_seconds=0)
    orch.run_one("survey", label="s", profile="scout")
    assert seen[-1]["model_role"] == "fast"
    assert seen[-1]["allowed_tools"] == ["read", "grep", "glob", "ls"]
    assert "subagent" not in seen[-1]["allowed_tools"]

    orch.run_one("build", label="b", profile="coder")
    assert seen[-1]["model_role"] == "coder"
    assert seen[-1]["allowed_tools"] == [
        "read", "write", "edit", "bash", "grep", "glob", "ls", "todo_write", "todo_read", "task",
    ]

    orch.run_one("jit", label="j")  # no profile at all
    assert seen[-1]["allowed_tools"] is None
