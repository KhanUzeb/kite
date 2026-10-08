"""Application contracts, policy/executor, verification, nested policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.agent.events import Event
from kite.agent.exceptions import Submitted
from kite.agent.verification import VerificationCollector
from kite.application.contracts import ModelSelection, RunSpec
from kite.application.dependencies import HarnessDependencies
from kite.application.events import InMemoryEventSink
from kite.application.execution import ChangeJournal, ProcessRunner, ToolExecutor
from kite.application.policy import ApprovalCoordinator, PolicyEngine, check_path_access, child_inherits_parent_policy
from kite.application.service import ApplicationRunService
from kite.application.state import RunState, can_transition
from kite.application.tools import ToolCall, derive_effects
from kite.application.verification import (
    CheckSpec,
    PackageUnit,
    VerificationRecord,
    WorkspaceProfile,
    build_verification_plan,
    html_parse_ok,
    next_required_check_command,
    plan_status,
    record_satisfies_check,
)
from kite.eval import ReplayBundle, run_replay


class _FakeHarness:
    def __init__(self, result: dict) -> None:
        self._result = result
        self._listeners: list = []

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def run(self, task: str, *, cancel=None) -> dict:
        for listener in self._listeners:
            listener(Event(kind="agent_start", payload={"task": task}))
            listener(Event(kind="agent_end", payload=self._result))
        return self._result


def test_service_maps_outcomes_and_sequences_events(workspace: Path) -> None:
    sink = InMemoryEventSink()
    service = ApplicationRunService()
    fake = _FakeHarness({"exit_status": "Submitted", "submission": "done", "cost": 0.1})
    result = service.run(RunSpec(task="demo", workspace=workspace, run_id="run-test", model_selection=ModelSelection(provider="fake")), deps=HarnessDependencies(event_sink=sink), harness=fake)  # type: ignore[arg-type]
    assert result.status == "completed" and result.stop_reason == "submitted"
    events = sink.load_run("run-test")
    assert [e.kind for e in events] == ["agent_start", "agent_end"]
    assert [e.sequence for e in events] == [1, 2]
    assert not fake._listeners
    failed = service.run(RunSpec(task="x", workspace=workspace), harness=_FakeHarness({"exit_status": "Error", "error": "boom"}))  # type: ignore[arg-type]
    assert failed.status == "failed"


def test_run_state_rejects_invalid_transitions() -> None:
    state = RunState("created")
    state.transition("prepared")
    state.transition("awaiting_model")
    state.transition("completed")
    assert state.terminal and not can_transition("completed", "awaiting_model")
    with pytest.raises(ValueError, match="invalid run transition"):
        RunState("created").transition("completed")


def test_approval_tiers_gate_only_risky_effects(tmp_path: Path) -> None:
    """auto/trust/yolo run on their own; supervised prompts for every mutation."""
    from kite.application.tools import tool_requires_approval_gate

    routine = [
        ("read", {"path": "a.py"}),
        ("grep", {"pattern": "x"}),
        ("write", {"path": "src/app.py", "content": "x"}),
        ("edit", {"path": "src/app.py", "old": "a", "new": "b"}),
        ("bash", {"command": "pytest -q"}),
        ("bash", {"command": "git commit -m x"}),
        ("bash", {"command": "npm run build"}),
    ]
    for tool, args in routine:
        for tier in ("auto", "trust", "yolo"):
            assert not tool_requires_approval_gate(tool, args, approval=tier), (tool, args, tier)
    for tool, args in routine:
        if tool in {"write", "edit", "bash"}:
            assert tool_requires_approval_gate(tool, args, approval="supervised"), tool

    risky = [
        ("bash", {"command": "rm -rf build/"}),
        ("bash", {"command": "curl http://x.com"}),
        ("bash", {"command": "pip install requests"}),
        ("websearch", {"query": "x"}),
        ("memory", {"action": "remember", "text": "x"}),
        ("subagent", {"prompt": "x"}),
    ]
    for tool, args in risky:
        assert tool_requires_approval_gate(tool, args, approval="auto"), (tool, args)
        assert tool_requires_approval_gate(tool, args, approval="yolo"), (tool, args)

    # The policy engine agrees, and the sandbox still refuses the escape.
    auto = PolicyEngine(tmp_path, approval="auto")
    write = ToolCall(call_id="w", name="write", arguments={"path": "src/app.py", "content": "x"})
    assert not auto.authorize(auto.derive_intent(write)).requires_approval
    sup = PolicyEngine(tmp_path, approval="supervised")
    assert sup.authorize(sup.derive_intent(write)).requires_approval
    outside = ToolCall(call_id="o", name="write", arguments={"path": "../evil.py", "content": "x"})
    decision = auto.authorize(auto.derive_intent(outside))
    assert decision.allowed and decision.requires_approval and decision.mandatory
    outside_read = ToolCall(call_id="r", name="read", arguments={"path": "../notes.txt"})
    allowed_read = auto.authorize(auto.derive_intent(outside_read))
    assert allowed_read.allowed and not allowed_read.requires_approval


def test_policy_paths_glob_executor_and_journal(workspace: Path, tmp_path: Path) -> None:
    ok, _ = check_path_access("../outside", workspace)
    assert not ok
    sibling = tmp_path / "proj-ok"
    evil = tmp_path / "proj-evil"
    sibling.mkdir()
    evil.mkdir()
    (evil / "secret.txt").write_text("no\n", encoding="utf-8")
    blocked, reason = check_path_access(evil / "secret.txt", sibling)
    assert not blocked
    other = tmp_path / "other"
    other.mkdir()
    target = other / "file.txt"
    target.write_text("ok\n", encoding="utf-8")
    allowed, _ = check_path_access(target, sibling, execution_mode="host")
    denied, _ = check_path_access(target, sibling, execution_mode="restricted")
    assert allowed and not denied
    engine = PolicyEngine(workspace)
    curl = ToolCall(call_id="1", name="bash", arguments={"command": "curl http://evil.com"})
    assert not engine.authorize(engine.derive_intent(curl)).allowed
    restricted = PolicyEngine(workspace, execution_mode="restricted")
    assert not restricted.authorize(restricted.derive_intent(curl)).allowed
    executor = ToolExecutor(policy=engine, runner=lambda c: {"ok": True, "output": "done"}, approver=lambda i, d: False)
    write = ToolCall(call_id="w1", name="write", arguments={"path": "src/app.py", "content": "x"})
    # auto: a routine in-workspace write is the agent's job, not a prompt.
    assert executor.execute(write).status == "ok"
    # supervised keeps the historical rule: prompt every mutation, deny when
    # nobody can approve.
    supervised = ToolExecutor(
        policy=PolicyEngine(workspace, approval="supervised"),
        runner=lambda c: {"ok": True, "output": "done"},
        approver=lambda i, d: False,
    )
    assert supervised.execute(write).status == "denied"
    assert executor.execute(write, skip_approval=True).ok
    # A risky effect still gates in auto, and is denied without an approver.
    risky = ToolCall(call_id="w2", name="bash", arguments={"command": "curl http://evil.com"})
    assert executor.execute(risky).status == "denied"
    def _raise(_call):
        raise Submitted({"role": "exit", "content": "done", "extra": {"exit_status": "Submitted"}})

    with pytest.raises(Submitted):
        ToolExecutor(policy=engine, runner=_raise).execute(ToolCall(call_id="s1", name="read", arguments={"path": "src/app.py"}), skip_approval=True)
    failed = ToolExecutor(policy=engine, runner=lambda c: {"ok": False, "returncode": 2, "output": "fail", "error": "fail"}).execute(
        ToolCall(call_id="b1", name="bash", arguments={"command": "pytest -q"}), skip_approval=True
    )
    assert failed.metadata.get("returncode") == 2
    invalid = ToolExecutor(policy=engine, runner=lambda c: []).execute(
        ToolCall(call_id="b2", name="bash", arguments={"command": "echo hi"}), skip_approval=True
    )
    assert invalid.status == "error" and "invalid result envelope" in invalid.error
    app = workspace / "src" / "app.py"
    original = app.read_text(encoding="utf-8")
    journal = ChangeJournal(workspace)
    journal.record_write(app)
    app.write_text("agent only\n", encoding="utf-8")
    journal.record_after_write(app)
    restored, conflicts = journal.restore()
    assert not conflicts and app.read_text(encoding="utf-8") == original
    journal.record_write(app)
    app.write_text("agent edit\n", encoding="utf-8")
    journal.record_after_write(app)
    app.write_text("user edit\n", encoding="utf-8")
    _, conflicts = journal.restore()
    assert conflicts and app.read_text(encoding="utf-8") == "user edit\n"
    # glob takes `root` (not `path`) — reads outside are free like every other reader.
    outside = tmp_path / "outside"
    outside.mkdir()
    denied_glob = engine.authorize(
        engine.derive_intent(ToolCall(call_id="g1", name="glob", arguments={"pattern": "**/*.py", "root": str(outside)}))
    )
    assert denied_glob.allowed and not denied_glob.requires_approval, denied_glob.reason
    inside = engine.authorize(
        engine.derive_intent(ToolCall(call_id="g2", name="glob", arguments={"pattern": "**/*.py", "root": str(workspace)}))
    )
    assert inside.allowed, inside.reason
    # Parity with the sibling readers: all allow the same outside read.
    for name, args in (
        ("read", {"path": str(outside / "secret.txt")}),
        ("grep", {"pattern": "x", "path": str(outside)}),
        ("ls", {"path": str(outside)}),
    ):
        decision = engine.authorize(engine.derive_intent(ToolCall(call_id="p1", name=name, arguments=args)))
        assert decision.allowed and not decision.requires_approval, (name, decision.reason)


def test_verification_plans_replay_and_package_paths(workspace: Path, tmp_path: Path) -> None:
    vc = VerificationCollector(workspace_root=str(workspace))
    vc.on_tool_end("bash", {"command": "pytest tests/ -q"}, {"ok": True, "returncode": 0, "output": "out"})
    assert any(a.kind == "test" for a in vc.artifacts) and vc.status() == "verified"
    idle = VerificationCollector(workspace_root=str(workspace))
    idle.on_tool_end("edit", {"path": "x.py"}, {"ok": True, "path": "x.py", "diff": "d"})
    assert idle.needs_tests()
    html = "<html><body>ok</body></html>"
    html_vc = VerificationCollector(workspace_root=str(workspace))
    html_vc.on_tool_end("write", {"path": "index.html", "content": html}, {"ok": True, "path": "index.html", "diff": "d", "content": html})
    assert not html_vc.needs_tests()
    assert html_parse_ok(html) and not html_parse_ok("<html><body>no closing tags")
    (workspace / "tests").mkdir(exist_ok=True)
    (workspace / "tests" / "test_app.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    python_vc = VerificationCollector(workspace_root=str(workspace))
    python_vc.on_tool_end("edit", {"path": "src/app.py"}, {"ok": True, "path": "src/app.py", "diff": "d"})
    cmd = next_required_check_command(python_vc)
    assert cmd and ("pytest" in cmd.lower() or "py_compile" in cmd.lower())
    evidence = VerificationCollector(workspace_root=str(tmp_path), run_id="run-ev")
    evidence.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "3 passed"})
    assert evidence.summary().get("evidence", {}).get("status") == "verified"
    html_plan = build_verification_plan(("dashboard.html",))
    assert not html_plan.required_checks  # markup is advisory-only, like docs
    assert html_plan.optional_checks and html_plan.optional_checks[0].artifact_kind == "html"
    assert all(c.command is None or "pytest" not in (c.command or "").lower() for c in html_plan.optional_checks)
    pytest_record = VerificationRecord(
        check=CheckSpec(kind="project_test", command="pytest -q", affected_paths=("a.py",), artifact_kind="python"),
        command="pytest -q",
        affected_paths=("a.py",),
        exit_status=0,
        ok=True,
        output_summary="1 passed",
    )
    assert not record_satisfies_check(pytest_record, html_plan.optional_checks[0])
    assert plan_status(build_verification_plan(("README",)), []) == "changed_unverified"
    bundle = ReplayBundle(
        run_id="acc-1",
        prompt_hash="h",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "Done — html updated."}],
        events=[{"kind": "verification_status", "payload": {"status": "verified"}}],
        acceptance={"content_contains": "html updated", "content_excludes": "pytest", "min_events": 1, "event_kinds": ["verification_status"]},
    )
    assert run_replay(bundle)["ok"]
    fail = ReplayBundle(
        run_id="acc-2", prompt_hash="h", context_snapshot_id="s", config_hash="c", model="fake", provider="fake",
        tool_catalog_hash="t", workspace_fingerprint="w", responses=[{"role": "assistant", "content": "nope"}],
        acceptance={"content_contains": "expected phrase"},
    )
    assert not run_replay(fail)["ok"]
    # Absolute package paths normalize to repo-relative.
    profile = WorkspaceProfile(
        workspace_root=str(tmp_path),
        packages=(
            PackageUnit(
                key="foo",
                root="packages/foo",
                ecosystems=frozenset({"python"}),
                test_command="cd packages/foo && pytest -q",
            ),
        ),
    )
    absolute = tmp_path / "packages" / "foo" / "src" / "app.py"
    plan = build_verification_plan((str(absolute),), profile=profile)
    assert plan.touched_paths == ("packages/foo/src/app.py",)
    assert len(plan.required_checks) == 1
    assert plan.required_checks[0].package_root == "packages/foo"
    assert plan.required_checks[0].command == "cd packages/foo && pytest -q"
    collector = VerificationCollector(workspace_root=str(tmp_path))
    collector.on_tool_end(
        "edit",
        {"path": str(absolute)},
        {"ok": True, "path": str(absolute), "diff": "d"},
    )
    assert collector.paths_touched == {"packages/foo/src/app.py"}
    assert collector.artifacts[-1].path == str(absolute)


def test_effects_coordinator_runner_and_cli_result(tmp_path: Path) -> None:
    import sys

    assert set(derive_effects(ToolCall("1", "bash", {"command": "rm -rf build"}))) == {"destructive", "long_running"}
    assert derive_effects(ToolCall("1", "memory", {"action": "remember", "text": "x"})) == ("durable_memory",)
    inherited = child_inherits_parent_policy(parent_approval="approve", parent_mode="build", parent_no_guardrails=False, parent_execution_mode="restricted", child_overrides={"approval": "yolo", "no_guardrails": True})
    assert inherited["approval"] == "approve" and inherited["no_guardrails"] is False
    locked = child_inherits_parent_policy(parent_approval="auto", parent_mode="plan", parent_no_guardrails=False, parent_execution_mode="restricted", child_overrides={"mode": "build", "execution_mode": "host"})
    assert locked["mode"] == "plan" and locked["execution_mode"] == "restricted"
    coord = ApprovalCoordinator(interactive=True, timeout_seconds=0.0)
    assert coord.request("bash", {"command": "curl x"}, mandatory=True) == "deny"
    assert coord.pending is None
    # Drain both pipes after their byte caps without retaining secret prefixes.
    prefix = "é" * 27 + " "  # 55 UTF-8 bytes; the token crosses the 64-byte cap.
    secret = "sk-" + "A" * 40
    script = (
        "import os\n"
        f"line = {(prefix + secret + chr(10)).encode()!r}\n"
        "os.write(1, line); os.write(2, line)\n"
        "for _ in range(128):\n"
        " os.write(1, b'x' * 4095 + b'\\n')\n"
        " os.write(2, b'y' * 4095 + b'\\n')\n"
    )
    capped = ProcessRunner(timeout_seconds=5.0, max_output_bytes=64)
    captured = capped.run([sys.executable, "-c", script])
    assert captured.exit_code == 0 and captured.truncated
    notice = "\n...[truncated]"
    for output in (captured.stdout, captured.stderr):
        assert output == prefix + "[REDACTED" + notice
        assert "sk-" not in output and "AAAA" not in output
        assert len(output.removesuffix(notice).encode()) == 64
    exact = capped.run([
        sys.executable, "-c",
        "import os, sys; os.write(1, ('é' * 32).encode()); os.write(2, b'e' * 64); sys.exit(3)",
    ])
    assert exact.exit_code == 3 and not exact.truncated
    assert exact.stdout == "é" * 32 and exact.stderr == "e" * 64
    oversized = capped.run([
        sys.executable, "-c",
        f"import sys; sys.stdout.write(' ' * 8190 + {secret!r} + '\\ndone\\n')",
    ])
    assert oversized.exit_code == 0 and oversized.truncated
    assert "oversized output line omitted" in oversized.stdout and "done\n" in oversized.stdout
    assert "sk-" not in oversized.stdout and "AAAA" not in oversized.stdout
    # 0.9 executor must resolve `python` from the project .venv like the bash tool.
    venv = tmp_path / ".venv"
    bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    bindir.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    (bindir / ("python.exe" if sys.platform == "win32" else "python")).write_text("")
    env = ProcessRunner._child_env(str(tmp_path))
    key = "Path" if sys.platform == "win32" and "Path" in env else "PATH"
    first = env[key].split(";" if sys.platform == "win32" else ":")[0]
    assert Path(first).resolve() == bindir.resolve()
    from kite.application.cli import CliResult
    from kite.application.contracts import RunResult
    from kite.application.service import _map_exit_status

    assert _map_exit_status("") == ("failed", "error")
    assert _map_exit_status(None) == ("failed", "error")
    assert _map_exit_status("LimitsExceeded") == ("failed", "limits_exceeded")
    submitted = RunResult(status="completed", stop_reason="submitted", final_message="ok")
    assert CliResult.from_run_result(submitted).ok is True
    unfinished = RunResult(status="completed", stop_reason="", final_message="still going")
    assert CliResult.from_run_result(unfinished).ok is False
    limited = RunResult(status="failed", stop_reason="limits_exceeded", final_message="steps")
    assert CliResult.from_run_result(limited).ok is False


def test_marker_and_prose_submit_skip_section_format(workspace: Path) -> None:
    """Marker/prose submits gate evidence only; the submit tool also gates sections."""

    vc = VerificationCollector(workspace_root=str(workspace))
    vc.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "1 passed"})
    assert vc.submit_block_reason("shipped the fix, tests pass", structured=False) is None
    assert vc.submit_block_reason("shipped the fix, tests pass", structured=True) is not None
    bare = VerificationCollector(workspace_root=str(workspace))
    bare.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    assert bare.submit_block_reason("shipped", structured=False) is not None  # evidence still gated
    assert "Suggested command" in (bare.submit_block_reason("shipped", structured=False) or "")


def test_failure_classification_and_bounded_submit_blocking(workspace: Path) -> None:
    """Failing checks are classified, and blocking is finite with an honest exit."""
    from kite.application.verification import (
        MAX_BLOCKED_SUBMITS,
        classify_failure,
        discloses_failures,
    )

    assert classify_failure(9009, "pytest : not recognized") == "runner_missing"
    assert classify_failure(127, "") == "runner_missing"
    assert classify_failure(1, "FAILED test_x - Timeout >30s") == "timeout"
    assert classify_failure(1, "Permission denied: build/app.o") == "environment"
    assert classify_failure(2, "ImportError while importing conftest") == "collection"
    assert classify_failure(1, "assert 1 == 2") == "assertion"
    assert discloses_failures("- ✗ pytest -q — 1 failed")
    assert discloses_failures("## Blocked\n- runner missing")
    assert not discloses_failures("- ✓ pytest -q — 1 passed")

    def _failing(output: str, rc: int = 1) -> VerificationCollector:
        vc = VerificationCollector(workspace_root=str(workspace))
        vc.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
        vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": False, "returncode": rc, "output": output})
        return vc

    report = "## Done\n- x\n\n## Changed\n- `a.py`\n\n## Verification\n- ✓ pytest -q"
    # A real assertion failure blocks, then reports why it will not clear.
    vc = _failing("FAILED tests/test_a.py::test_x - AssertionError")
    first = vc.submit_block_reason(report)
    assert first and "Suggested command" in first
    vc.begin_turn()
    second = vc.submit_block_reason(report)
    assert second and "Blocked 2 of" in second
    # A later pass clears only that command's failure.
    vc.begin_turn()
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "1 passed"})
    assert vc.failures == [] and vc.submit_block_reason(report) is None

    # A missing runner cannot be fixed by retrying — one block, then honesty passes.
    missing = _failing("pytest : The term 'pytest' is not recognized", rc=9009)
    assert missing.failures[0].unfixable
    assert missing.submit_block_reason(report) is not None
    honest = ("## Done\n- x\n\n## Changed\n- `a.py`\n\n"
              "## Blocked\n- pytest is not installed in this environment")
    assert missing.submit_block_reason(honest) is None

    # A fixable failure still gets the retries, then accepts the honest report.
    stuck = _failing("FAILED tests/test_a.py::test_x - AssertionError")
    blocked = []
    for _ in range(MAX_BLOCKED_SUBMITS):
        stuck.begin_turn()
        blocked.append(stuck.submit_block_reason(report))
    assert all(blocked), "an honesty-free report must not pass early"
    assert stuck.submit_exhausted
    assert stuck.submit_block_reason(honest) is None
    # Re-gating inside one turn is one attempt, not two (loop + `submit` tool).
    once = _failing("FAILED tests/test_a.py::test_x - AssertionError")
    once.begin_turn()
    assert once.submit_block_reason(report) and once.submit_block_reason(report)
    assert once.blocked_submits == 1


def test_compaction_trigger_scales_with_window() -> None:
    """The trigger and its reserve must scale with the model's context window.

    A flat 0.75 on a 1M window compacts at 750k tokens and then runs the
    summarization call against that same 750k transcript — the cost the trigger
    exists to avoid. The ratio clause has to move down as the window grows, and
    the edge reserve up, while an explicit TOML value still wins.
    """
    from kite.context.window import (
        ContextUsage,
        scale_compact_ratio,
        scale_compaction_llm_ratio,
        scale_reserve_tokens,
        should_compact,
    )

    def usage_at(total: int, window: int) -> ContextUsage:
        return ContextUsage(
            total_tokens=total,
            system_tokens=0,
            message_tokens=total,
            tool_tokens=0,
            message_count=8,
            window=window,
        )

    # Reserve: ~6% of the window, floor 4k. Small windows get the floor.
    assert scale_reserve_tokens(32_000, 0) == 4_000
    assert scale_reserve_tokens(128_000, 0) == 7_680
    assert scale_reserve_tokens(1_000_000, 0) == 60_000
    # A user-set floor is never reduced by scaling.
    assert scale_reserve_tokens(1_000_000, 12_288) == 60_000
    assert scale_reserve_tokens(32_000, 12_288) == 12_288

    # Ratio: unchanged at and below the 128k reference, lower above it.
    assert scale_compact_ratio(128_000, 0) == 0.75
    assert scale_compact_ratio(256_000, 0) == 0.70
    assert scale_compact_ratio(512_000, 0) == 0.65
    assert scale_compact_ratio(1_000_000, 0) == 0.65
    # Never below the floor, however large the window.
    assert scale_compact_ratio(8_000_000, 0) >= 0.55
    # A user's flat value is pinned regardless of window.
    assert scale_compact_ratio(1_000_000, 0.75) == 0.75

    # The reported bug: on 1M, auto triggers well before 750k.
    first = next(t for t in range(0, 1_000_000, 5_000) if should_compact(usage_at(t, 1_000_000)))
    assert first == 650_000, first
    # Pinning the old flat ratio reproduces the old behaviour exactly.
    assert not should_compact(usage_at(749_000, 1_000_000), ratio=0.75)
    assert should_compact(usage_at(751_000, 1_000_000), ratio=0.75)

    # The LLM summarizer threshold tracks the trigger instead of sitting at 0.92.
    assert scale_compaction_llm_ratio(128_000, 0) == 0.92
    assert scale_compaction_llm_ratio(1_000_000, 0) == 0.82
    assert scale_compaction_llm_ratio(1_000_000, 0.92) == 0.92
    # It must stay above the trigger, whatever the window.
    for window in (32_000, 128_000, 256_000, 1_000_000, 4_000_000):
        assert scale_compaction_llm_ratio(window, 0) > scale_compact_ratio(window, 0), window

    # window=0 means unknown: never compact, never divide by zero.
    assert should_compact(usage_at(999_999, 0)) is False
    assert scale_compact_ratio(0, 0) == 0.75
    assert scale_reserve_tokens(0, 0) == 12_288
    assert scale_compaction_llm_ratio(0, 0) == 0.92
