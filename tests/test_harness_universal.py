"""Consolidated harness contract tests — effects, plans, policy, platform, cache, events."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from kite.agent.runtime import AgentRuntime, RuntimeOptions
from kite.application.events import EventSequencer
from kite.application.policy import ApprovalCoordinator, PolicyEngine, child_inherits_parent_policy
from kite.application.tools import ToolCall, ToolResult
from kite.application.tools.effects import derive_effects, normalize_legacy_effect, tool_requires_approval_gate
from kite.application.ui import ReplEventReducer
from kite.application.verification import EvidenceVerifier
from kite.application.verification.plan import (
    CheckSpec,
    VerificationRecord,
    build_verification_plan,
    classify_path,
    plan_status,
    record_satisfies_check,
)
from kite.eval import ReplayBundle, run_replay
from kite.memory.session import create_session
from kite.models.cache import CacheStats, PromptCacheManager
from kite.providers.capabilities import agent_model_warning, platform_shell_hint


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("skill", {"name": "debug"}, ("workspace_read",)),
        ("skill", {"install": "some-pack"}, ("package_or_skill_install",)),
        ("memory", {"action": "remember", "text": "x"}, ("durable_memory",)),
        ("memory", {"action": "list"}, ("workspace_read",)),
        ("task", {"prompt": "x"}, ("long_running", "nested_agent")),
        ("bash", {"command": "curl https://example.com"}, ("long_running", "network")),
        ("bash", {"command": "rm -rf build"}, ("destructive", "long_running")),
    ],
)
def test_derive_effects(tool: str, args: dict, expected: tuple[str, ...]) -> None:
    assert derive_effects(ToolCall("1", tool, args)) == expected


def test_legacy_effect_mapping_and_policy(workspace) -> None:
    assert normalize_legacy_effect("read") == "workspace_read"
    assert normalize_legacy_effect("process_control") == "long_running"
    engine = PolicyEngine(workspace)
    call = ToolCall("1", "bash", {"command": "curl http://evil.com"})
    assert not engine.authorize(engine.derive_intent(call)).allowed


@pytest.mark.parametrize(
    ("paths", "kind", "no_pytest"),
    [
        (("dashboard.html",), "html", True),
        (("src/kite/foo.py",), "python", False),
        (("README",), None, True),
    ],
)
def test_verification_plan_selection(paths: tuple[str, ...], kind: str | None, no_pytest: bool) -> None:
    plan = build_verification_plan(paths)
    if kind:
        assert plan.required_checks
        assert plan.required_checks[0].artifact_kind == kind
    else:
        assert plan.required_checks == ()
        assert plan_status(plan, []) == "changed_unverified"
    if no_pytest:
        assert all(c.command is None or "pytest" not in (c.command or "").lower() for c in plan.required_checks)


def test_unrelated_pass_does_not_satisfy_html_check() -> None:
    plan = build_verification_plan(("index.html",))
    html_check = plan.required_checks[0]
    pytest_record = VerificationRecord(
        check=CheckSpec(kind="project_test", command="pytest -q", affected_paths=("a.py",), artifact_kind="python"),
        command="pytest -q",
        affected_paths=("a.py",),
        exit_status=0,
        ok=True,
        output_summary="1 passed",
    )
    assert not record_satisfies_check(pytest_record, html_check)
    assert classify_path("x.py") == "python"
    assert classify_path("x.html") == "html"


@pytest.mark.parametrize(
    ("parent_approval", "child_overrides", "expected_approval", "expected_guardrails"),
    [
        ("approve", {"approval": "yolo"}, "approve", False),
        ("auto", {"no_guardrails": True}, "auto", False),
        ("approve", {}, "approve", False),
    ],
)
def test_nested_policy_inheritance(
    parent_approval: str,
    child_overrides: dict,
    expected_approval: str,
    expected_guardrails: bool,
) -> None:
    inherited = child_inherits_parent_policy(
        parent_approval=parent_approval,
        parent_mode="build",
        parent_no_guardrails=False,
        parent_execution_mode="restricted",
        child_overrides=child_overrides or None,
    )
    assert inherited["approval"] == expected_approval
    assert inherited["no_guardrails"] is expected_guardrails


def test_nested_cannot_elevate_mode_or_execution() -> None:
    inherited = child_inherits_parent_policy(
        parent_approval="auto",
        parent_mode="plan",
        parent_no_guardrails=False,
        parent_execution_mode="restricted",
        child_overrides={"mode": "build", "execution_mode": "host"},
    )
    assert inherited["mode"] == "plan"
    assert inherited["execution_mode"] == "restricted"


def test_approval_coordinator_rejects_concurrent_request() -> None:
    coord = ApprovalCoordinator(interactive=True, timeout_seconds=5.0)
    results: dict[str, str] = {}

    def first() -> None:
        results["first"] = coord.request("bash", {"command": "rm a"}, mandatory=True)

    t1 = threading.Thread(target=first)
    t1.start()
    for _ in range(50):
        if coord.pending is not None:
            break
        time.sleep(0.01)
    results["second"] = coord.request("bash", {"command": "rm b"}, mandatory=True)
    assert coord.resolve("allow", request_id=coord.pending.request_id)
    t1.join(timeout=2)
    assert results["second"] == "deny"
    assert results["first"] == "allow"
    assert coord.pending is None


def test_approval_timeout_clears_pending() -> None:
    coord = ApprovalCoordinator(interactive=True, timeout_seconds=0.05)
    assert coord.request("bash", {"command": "curl x"}, mandatory=True) == "deny"
    assert coord.pending is None


def test_resolve_rejects_wrong_request_id() -> None:
    coord = ApprovalCoordinator(interactive=True, timeout_seconds=5.0)

    def block() -> None:
        coord.request("bash", {"command": "rm x"}, mandatory=True)

    t = threading.Thread(target=block)
    t.start()
    for _ in range(50):
        if coord.pending is not None:
            break
        time.sleep(0.01)
    assert not coord.resolve("allow", request_id="stale-id")
    assert coord.resolve("allow", request_id=coord.pending.request_id)
    t.join(timeout=2)
    assert coord.pending is None


def test_html_pytest_does_not_satisfy_html_plan() -> None:
    from kite.agent.verification import VerificationCollector

    vc = VerificationCollector()
    vc.on_tool_end(
        "edit",
        {"path": "index.html"},
        {"ok": True, "path": "index.html", "diff": "<html><body>broken"},
    )
    assert vc.needs_tests()
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "1 passed"})
    assert vc.status() != "verified"


def test_html_empty_content_does_not_verify() -> None:
    from kite.agent.verification import VerificationCollector

    vc = VerificationCollector()
    vc.on_tool_end("edit", {"path": "index.html"}, {"ok": True, "path": "index.html", "diff": ""})
    assert vc.needs_tests()


def test_approval_gate_and_coordinator() -> None:
    assert tool_requires_approval_gate("memory", {"action": "remember", "text": "x"})
    assert tool_requires_approval_gate("skill", {"install": "pkg"})
    coord = ApprovalCoordinator(interactive=True)
    results: list[str] = []

    def worker() -> None:
        results.append(coord.request("bash", {"command": "rm x"}, reason="destructive", mandatory=True))

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(50):
        if coord.pending is not None:
            break
        time.sleep(0.01)
    assert coord.pending is not None
    coord.resolve("allow")
    t.join(timeout=2)
    assert results == ["allow"]
    assert ApprovalCoordinator(interactive=False).request("bash", {"command": "curl x"}, mandatory=True) == "deny"


@pytest.mark.parametrize(
    ("model", "expect_warning"),
    [("text-embedding-3-small", True), ("claude-sonnet-4", False)],
)
def test_model_capability_warnings(model: str, expect_warning: bool) -> None:
    warning = agent_model_warning(model)
    if expect_warning:
        assert warning is not None
        assert "tool" in warning.lower()
    else:
        assert warning is None


@pytest.mark.parametrize(
    ("platform", "needle"),
    [("win32", "Windows"), ("linux", "POSIX")],
)
def test_platform_shell_hint(monkeypatch, platform: str, needle: str) -> None:
    monkeypatch.setattr("sys.platform", platform)
    assert needle in platform_shell_hint()


def test_prompt_cache_session_stats(kite_home, tmp_path) -> None:
    disabled = PromptCacheManager("anthropic", enabled=False).summary()
    assert disabled["cache_hit_tokens"] == 0
    assert disabled["calls"] == 0

    mgr = PromptCacheManager("anthropic", enabled=True)

    class _Usage:
        prompt_tokens = 100
        completion_tokens = 20
        cache_read_input_tokens = 80

    mgr.record(_Usage())
    assert mgr.summary()["cache_hit_tokens"] == 80
    assert hasattr(mgr, "session") and not hasattr(mgr, "stats")

    runtime = AgentRuntime(RuntimeOptions(cwd=str(tmp_path)))
    session = create_session(task="cache", cwd=str(tmp_path), provider="groq", model="test")
    cache = PromptCacheManager("groq", enabled=True)
    cache.session = CacheStats(cache_read_tokens=42, calls=1)
    agent = SimpleNamespace(
        model=SimpleNamespace(prompt_cache=cache),
        last_usage_estimate=None,
        mode=None,
        approval=None,
        tool_call_count=0,
        tool_counts={},
        n_calls=1,
        cost=0.0,
    )
    runtime._persist_session_stats(session, {"exit_status": "Submitted"}, agent=agent)
    from kite.memory.session_analytics import load_session_stats

    saved = load_session_stats(session.id)
    assert saved is not None
    assert saved.cache_hit_tokens == 42


def test_reducer_verification_submit_and_replay() -> None:
    reducer = ReplEventReducer()
    seq = EventSequencer("accept-1")
    reducer.apply(seq.emit("agent_start", {"task": "edit html"}))
    reducer.apply(seq.emit("verification_plan", {"artifact_kinds": ["html"], "required_checks": 1}))
    reducer.apply(seq.emit("verification_record", {"ok": True, "artifact_kind": "html"}))
    reducer.apply(seq.emit("submit_blocked", {"reason": "claims without evidence"}))
    assert reducer.snapshot()["status"] == "blocked"

    seq2 = EventSequencer("accept-2")
    reducer.apply(seq2.emit("approval_request", {"request_id": "a1", "tool": "bash"}))
    assert reducer.snapshot()["status"] == "awaiting_approval"
    reducer.apply(seq2.emit("approval_decision", {"request_id": "a1", "decision": "allow"}))
    assert reducer.snapshot()["status"] == "running"

    bundle = ReplayBundle(
        run_id="transcript-1",
        prompt_hash="h",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "Done — html updated."}],
    )
    out = run_replay(bundle)
    assert out["ok"] and "Done" in out["content"]
    assert "pytest" not in out["content"].lower()


def test_evidence_verifier_claims() -> None:
    v = EvidenceVerifier("run-1")
    record = v.consume(
        ToolResult(call_id="c1", status="ok", ok=True, output="3 passed", metadata={"command": "pytest -q", "exit_code": 0}),
        command="pytest -q",
        cwd="/proj",
    )
    assert record and record.status == "passed"
    assert v.verification_status()["status"] == "verified"
    assert not EvidenceVerifier("run-2").model_claim_satisfies("All tests pass!")
    v3 = EvidenceVerifier("run-3")
    v3.consume(ToolResult(call_id="c1", status="ok", ok=True, metadata={"command": "pytest", "exit_code": 0}), command="pytest")
    assert v3.model_claim_satisfies("tests pass")
