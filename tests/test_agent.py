"""Agent loop, modes, completion, cancel, dispatch, recovery, submit gate."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from kite.agent.cancel import CancelToken
from kite.agent.compaction import CompactionConfig, LoopCompactor
from kite.agent.dispatch_mode import resolve_dispatch_mode
from kite.agent.exceptions import LimitsExceeded, ProviderFault, Submitted
from kite.agent.harness_build import build_harness_config
from kite.agent.loop import (
    _MAX_IDLE_TURNS,
    DefaultAgent,
    text_submission,
)
from kite.agent.loop_guard import LoopGuard, is_unexpected_stop
from kite.agent.mode import (
    MUTATING_TOOLS,
    PARALLEL_SAFE_TOOLS,
    PLAN_TOOLS,
    READONLY_TOOLS,
    AgentMode,
    is_parallel_safe,
    tools_for_mode,
    tools_for_nested_subagent,
)
from kite.agent.queue import RunMessageQueue
from kite.agent.verification import VerificationCollector
from kite.env.local import LocalEnvironment
from kite.memory.goal import SessionGoal, load_session_goal, save_session_goal
from kite.memory.recovery import build_recovery_follow_up, decide_recovery_continue, should_auto_recover
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


class _StubModel:
    resolved = type("R", (), {"provider": "test", "model": "m"})()

    def format_message(self, role: str, content: str = "", extra=None, **kwargs):
        return {"role": role, "content": content}

    def query(self, messages):
        raise AssertionError("should not query after limit")

    def format_observation_messages(self, message, outputs, template_vars=None):
        return [{"role": "tool", "content": str(outputs)}]


class _FlakyModel(_StubModel):
    def __init__(self) -> None:
        self.calls = 0

    def query(self, messages):
        self.calls += 1
        if self.calls < 3:
            raise TimeoutError("connection timed out")
        return {"role": "assistant", "content": "done", "extra": {"cost": 0.0}}


class _TextOnlyModel:
    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages):
        return {"role": "assistant", "content": "I finished the refactor.", "extra": {"actions": [], "cost": 0.0}}

    def format_observation_messages(self, message, outputs, template_vars=None):
        return [{"role": "tool", "content": str(outputs)}]


class _StubEnv:
    def execute(self, action: dict, cwd: str = "") -> dict:
        return {"ok": True, "output": ""}


def test_query_limits_retry_fault_and_budget_guard(monkeypatch) -> None:
    monkeypatch.setattr("kite.agent.loop.retry_delay_s", lambda attempt, **kwargs: 0)
    model = _StubModel()
    agent = DefaultAgent(model, LocalEnvironment(registry=ToolRegistry([])), step_limit=2, cost_limit=5.0)
    agent.n_calls = 2
    agent.messages = [model.format_message("user", content="hi")]
    with pytest.raises(LimitsExceeded) as ei:
        agent.query()
    assert ei.value.messages[0]["extra"].get("limit_kind") == "steps"
    agent = DefaultAgent(model, LocalEnvironment(registry=ToolRegistry([])), step_limit=40, cost_limit=1.0)
    agent.cost = 1.0
    agent.messages = [model.format_message("user", content="hi")]
    with pytest.raises(LimitsExceeded) as ei:
        agent.query()
    assert ei.value.messages[0]["extra"].get("limit_kind") == "cost"
    events: list[str] = []
    flaky = _FlakyModel()
    ok = DefaultAgent(
        flaky,
        LocalEnvironment(registry=ToolRegistry([])),
        provider_max_retries=4,
        step_limit=1,
        on_event=lambda e: events.append(e.kind),
    )
    ok.messages = [flaky.format_message("system", content="sys"), flaky.format_message("user", content="hi")]
    assert ok.query()["content"] == "done"
    assert flaky.calls == 3 and "provider_retry" in events
    exhausted = _FlakyModel()
    bad = DefaultAgent(exhausted, LocalEnvironment(registry=ToolRegistry([])), provider_max_retries=2)
    bad.messages = [exhausted.format_message("user", content="hi")]
    with pytest.raises(ProviderFault):
        bad.query()
    budget_events: list[str] = []

    def _over_budget(**kwargs) -> DefaultAgent:
        budgeted = DefaultAgent(_StubModel(), _StubEnv(), on_event=lambda e: budget_events.append(e.kind), **kwargs)
        budgeted.env.execute = lambda action, cwd="": (_ for _ in ()).throw(AssertionError("tool must not dispatch"))  # type: ignore[method-assign]
        return budgeted

    stepped = _over_budget(step_limit=2)
    stepped.n_calls = 2
    stepped.execute_actions(
        {"role": "assistant", "content": "", "extra": {"actions": [{"tool": "read", "arguments": {"path": "x"}}]}}
    )
    costed = _over_budget(cost_limit=1.0)
    costed.cost = 1.0
    costed.execute_actions(
        {"role": "assistant", "content": "", "extra": {"actions": [{"tool": "read", "arguments": {"path": "x"}}]}}
    )
    assert "limits" in budget_events
    for budgeted in (stepped, costed):
        blob = "\n".join(str(m.get("content") or "") for m in budgeted.messages)
        assert "budget" in blob


def test_compaction_preserves_history(workspace: Path) -> None:
    from kite.memory.compaction_ops import run_compaction

    msgs = [{"role": "system", "content": "s"}]
    msgs += [{"role": "user", "content": "word " * 4000}] * 6
    result = run_compaction(
        msgs, window=8_000, reserve_tokens=1_000, keep_recent_tokens=200,
        force=True, session_id="sess-1", cwd=str(workspace),
    )
    assert result.compacted
    assert (workspace / ".kite" / "history").is_dir()
    assert any("Full history:" in str(m.get("content") or "") for m in result.messages)


def test_loop_guard_warns_and_hard_stops() -> None:
    guard = LoopGuard(repeat_threshold=3)
    mutating = {"command": "make build"}
    for _ in range(2):
        assert guard.record("bash", mutating).warning is None
    warning = guard.record("bash", mutating)
    assert warning.warning and "same arguments" in warning.warning
    grep = LoopGuard(repeat_threshold=3)
    grep_args = {"pattern": "foo"}
    for _ in range(5):
        assert grep.record("grep", grep_args).warning is None
    assert grep.record("grep", grep_args).warning is not None
    progress = LoopGuard(repeat_threshold=3, hard_threshold=5)
    pending = {"command": "curl -s localhost/status"}
    progress.record("bash", pending, {"ok": True, "output": "pending"})
    progress.record("bash", pending, {"ok": True, "output": "pending"})
    assert progress.record("bash", pending, {"ok": True, "output": "ready"}).warning is None
    hard = LoopGuard(repeat_threshold=2, hard_threshold=4)
    for _ in range(3):
        hard.record("bash", mutating, {"ok": True, "output": "same"})
    assert hard.record("bash", mutating, {"ok": True, "output": "same"}).hard_stop


def test_schema_repair_nudge_names_expected_keys(workspace: Path) -> None:
    tools = make_coding_tools(cwd=str(workspace), enabled=["read"])
    repair_agent = DefaultAgent(_StubModel(), LocalEnvironment(registry=ToolRegistry(tools)))
    tool, args, action = repair_agent._prepare_action({"tool": "read", "arguments": "x.py"})
    assert args == {}
    hint = str(action.get("_schema_repair_hint") or "")
    assert "arguments must be an object" in hint and "path" in hint
    outputs: list[dict] = []
    repair_agent._after_tool(tool, args, action, {"ok": False, "error": "boom", "output": "boom"}, 1, outputs)
    assert "Schema repair" in outputs[0]["output"] and "path" in outputs[0]["output"]


def test_unexpected_stop_classifier() -> None:
    assert is_unexpected_stop("I'll inspect the failing test next.")
    assert is_unexpected_stop("Let me fix the import now.")
    assert not is_unexpected_stop("The task is complete.")
    assert not is_unexpected_stop("Should I continue?")


def test_informational_turn_returns_answer_not_report() -> None:
    # Issue #81: informational turns end with the answer, not a turn report.
    agent = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    agent.messages = [{"role": "user", "content": "tell main features of kite"}]
    with pytest.raises(Submitted) as ei:
        agent.execute_actions({"role": "assistant", "content": "Kite features: fast runs", "extra": {"actions": []}})
    assert ei.value.messages[0].get("content") == "Kite features: fast runs"
    assert "## Verification" not in (ei.value.messages[0].get("content") or "")


def test_completion_idle_and_error_stop(monkeypatch) -> None:
    gated = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    gated.messages = [{"role": "user", "content": "run the test suite"}]
    gated.execute_actions({"role": "assistant", "content": "All tests pass. Task complete.", "extra": {"actions": []}})
    blob = "\n".join(str(m.get("content") or "") for m in gated.messages)
    assert "Submit blocked" in blob or "claims" in blob.lower()
    idle = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    idle.verification.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    for _ in range(_MAX_IDLE_TURNS + 1):
        idle.execute_actions({"role": "assistant", "content": "thinking", "extra": {"actions": []}})
    assert "verification" in "\n".join(str(m.get("content") or "") for m in idle.messages).lower()
    stall = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    for _ in range(_MAX_IDLE_TURNS):
        stall.execute_actions({"role": "assistant", "content": "thinking", "extra": {"actions": []}})
    assert stall.messages[-1].get("extra", {}).get("exit_status") == "Stalled"
    assert stall.messages[-1].get("extra", {}).get("submission") == "thinking"

    class _Boom:
        def format_message(self, **kwargs):
            return dict(kwargs)

        def query(self, messages):
            raise RuntimeError("provider exploded")

        def format_observation_messages(self, message, outputs, template_vars=None):
            return []

    boom = DefaultAgent(_Boom(), _StubEnv(), interactive=False, mode=AgentMode.BUILD, provider_max_retries=1)
    monkeypatch.setattr("kite.agent.loop.is_transient_provider_error", lambda _e: False)
    result = boom.run("do something")
    assert result.get("exit_status") == "Error"


def test_text_submit_marker_ends_the_turn() -> None:
    # Regression: a provider dropped the tool call and the model wrote
    # COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT as prose. That used to be counted as an
    # idle turn and the run ended Stalled after three nudges, hiding finished work.
    agent = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    agent.messages = [{"role": "user", "content": "can you create a tetris game in html"}]
    report = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n\n## Done\n- created `game_tetris/index.html`"
    with pytest.raises(Submitted) as ei:
        agent.execute_actions({"role": "assistant", "content": report, "extra": {"actions": []}})
    extra = ei.value.messages[0].get("extra") or {}
    assert extra.get("exit_status") == "Submitted"
    assert extra.get("submission") == "## Done\n- created `game_tetris/index.html`"

    leaked = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    leaked.messages = [{"role": "user", "content": "run the tests"}]
    with pytest.raises(Submitted):
        leaked.execute_actions(
            {"role": "assistant", "content": 'all good\n<submit message="## Done\n- ran pytest"></submit>', "extra": {"actions": []}}
        )

    assert text_submission("just a normal reply") == ""
    assert is_unexpected_stop("Thanks! Let me know if you want tweaks") is False


def test_submit_tool_call_accounting(workspace: Path) -> None:

    class _SubmitModel:
        def format_message(self, **kwargs):
            return dict(kwargs)

        def query(self, messages):
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_submit", "type": "function", "function": {"name": "submit", "arguments": "{}"}}
                ],
                "extra": {
                    "actions": [{"tool": "submit", "id": "call_submit", "arguments": {"message": "done"}}],
                    "cost": 0.0,
                },
            }

        def format_observation_messages(self, message, outputs, template_vars=None):
            actions = message.get("extra", {}).get("actions", [])
            return [
                {"role": "tool", "tool_call_id": action["id"], "content": str(output)}
                for action, output in zip(actions, outputs, strict=False)
            ]

    class _SubmitEnv:
        def execute(self, action, cwd=""):
            raise Submitted({"role": "exit", "content": "submitted", "extra": {"exit_status": "Submitted"}})

    submit_agent = DefaultAgent(_SubmitModel(), _SubmitEnv(), step_limit=2)
    result = submit_agent.run("do it")
    assert result.get("exit_status") == "Submitted"  # no-edit submit closes freely
    transcript = [m for m in submit_agent.messages if m.get("role") != "exit"]
    calls = [tc["id"] for m in transcript if m.get("tool_calls") for tc in m["tool_calls"]]
    answered = [m.get("tool_call_id") for m in transcript if m.get("role") == "tool"]
    assert calls == ["call_submit"]
    assert answered == ["call_submit"]  # success still answers the tool call
    from kite.agent.exceptions import Interrupted

    class _PairModel:
        def format_observation_messages(self, message, outputs, template_vars=None):
            actions = message.get("extra", {}).get("actions", [])
            return [
                {"role": "tool", "tool_call_id": action["id"], "content": str(output.get("output"))}
                for action, output in zip(actions, outputs, strict=False)
            ]

    def _turn(*names: str) -> dict:
        actions = [{"tool": name, "id": f"call_{i}", "arguments": {"path": "a.py"}} for i, name in enumerate(names)]
        return {"role": "assistant", "content": "", "extra": {"actions": actions}}

    interrupted = DefaultAgent(_PairModel(), LocalEnvironment(registry=ToolRegistry(make_coding_tools(cwd=str(workspace), enabled=["read"]))), step_limit=3)
    interrupted._interrupt = True
    with pytest.raises(Interrupted):
        interrupted.execute_actions(_turn("read", "read", "read"))
    answered = [m.get("tool_call_id") for m in interrupted.messages if m.get("role") == "tool"]
    assert answered == ["call_0", "call_1", "call_2"]

    class _SubmitEnv2:
        def execute(self, action, cwd=""):
            if action.get("tool") == "submit":
                raise Submitted({"role": "exit", "content": "submitted"})
            return {"ok": True, "output": "saw file"}

    follow = DefaultAgent(_PairModel(), _SubmitEnv2(), step_limit=3)
    with pytest.raises(Submitted):
        follow.execute_actions(_turn("read", "submit"))
    answered = [m.get("tool_call_id") for m in follow.messages if m.get("role") == "tool"]
    assert answered == ["call_0", "call_1"]


def test_submit_gate_and_verification(workspace: Path) -> None:
    class _EditThenSubmit:
        def __init__(self) -> None:
            self.step = 0

        def format_message(self, **kwargs):
            return dict(kwargs)

        def query(self, messages):
            self.step += 1
            if self.step == 1:
                return {"role": "assistant", "content": "", "extra": {"actions": [{"tool": "edit", "id": "e1", "arguments": {"path": "a.py", "old_string": "a", "new_string": "b"}}], "cost": 0.0}}
            return {
                "role": "assistant",
                "content": "",
                "extra": {
                    "actions": [{"tool": "bash", "id": "call_1", "arguments": {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n## Done\n- x\n## Changed\n- `a.py`\n## Verification\n- ✓ done"}}],
                    "cost": 0.0,
                },
            }

        def format_observation_messages(self, message, outputs, template_vars=None):
            return [{"role": "tool", "tool_call_id": "call_1", "content": str(outputs)}]

    class _Env:
        def execute(self, action, cwd=""):
            if action.get("tool") == "edit":
                return {"ok": True, "path": "a.py", "diff": "--- a\n+++ b", "output": "edited"}
            cmd = str((action.get("arguments") or {}).get("command") or "")
            if "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in cmd:
                raise Submitted({"role": "exit", "content": "submitted", "extra": {"exit_status": "Submitted", "submission": cmd}})
            return {"ok": True, "output": ""}

    agent = DefaultAgent(_EditThenSubmit(), _Env(), verify_before_submit=True, step_limit=3, approver=lambda *_a, **_k: "allow")
    agent.run("fix a.py")
    assert "Submit blocked" in "\n".join(str(m.get("content") or "") for m in agent.messages)
    vc = VerificationCollector()
    vc.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    vc.on_tool_end("bash", {"command": "pytest -q"}, {"ok": True, "returncode": 0, "output": "1 passed"})
    submission = "## Done\n- x\n## Changed\n- `a.py`\n## Verification\n- ✓ pytest -q"
    assert vc.submit_block_reason(submission) is None
    from kite.application.execution import build_tool_executor

    env = LocalEnvironment(cwd=str(workspace), registry=ToolRegistry(make_coding_tools(cwd=str(workspace), enabled=["read"])))
    executor = build_tool_executor(workspace_root=workspace, execution_mode="restricted", no_guardrails=False, runner=lambda call: env.execute({"tool": call.name, "arguments": dict(call.arguments)}))
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    gated = DefaultAgent(MagicMock(), env, tool_executor=executor)
    blocked = gated._run_gated_via_executor(
        "read",
        {"path": "../outside.txt"},
        {"tool": "read", "arguments": {"path": "../outside.txt"}},
    )
    assert blocked.get("ok") is True  # outside reads are free; writes need approval
    denied = DefaultAgent(MagicMock(), MagicMock(), tool_executor=None)._run_gated("write", {"path": "outside.txt", "content": "x"}, {})
    assert denied.get("blocked") is True
    inspect = DefaultAgent(MagicMock(), MagicMock(), tool_executor=build_tool_executor(workspace_root=workspace, execution_mode="host", no_guardrails=False, runner=lambda call: {"ok": True, "output": "clean"}), mode=AgentMode.PLAN)
    assert inspect._run_gated_via_executor(
        "bash",
        {"command": "git status"},
        {"tool": "bash", "arguments": {"command": "git status"}},
    ).get("ok") is True
    submit_agent = DefaultAgent(_StubModel(), _StubEnv(), verify_before_submit=True)
    submit_agent.verification.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    blocked_submit = submit_agent._invoke_tool(
        "submit", {"message": "finished"}, {"tool": "submit", "arguments": {"message": "finished"}}
    )
    assert blocked_submit.get("blocked") is True and "Submit blocked" in str(blocked_submit.get("error") or "")
    clean = DefaultAgent(_StubModel(), _StubEnv(), verify_before_submit=True)
    assert clean.verification.submit_block_reason("hi") is None


def test_submit_gate_stops_instead_of_looping() -> None:
    # Regression: the agent writes its own test, that test fails, submit is blocked,
    # and the model rewords its report each turn — so no dedupe caught it and the
    # run burned the whole step budget before finally reporting.
    from kite.application.verification import MAX_BLOCKED_SUBMITS

    passing = "## Done\n- x\n\n## Changed\n- `a.py`\n\n## Verification\n- ✓ pytest -q"
    honest = (
        "## Done\n- x\n\n## Changed\n- `a.py`\n\n"
        "## Verification\n- ✗ pytest -q — my new test still fails\n\n"
        "## Blocked\n- tests/test_a.py::test_x assertion fails"
    )

    class _Env:
        def execute(self, action, cwd=""):
            if action.get("tool") == "edit":
                return {"ok": True, "path": "a.py", "diff": "d", "output": "edited"}
            cmd = str((action.get("arguments") or {}).get("command") or "")
            if "pytest" in cmd:
                return {"ok": False, "returncode": 1,
                        "output": "1 failed\nFAILED tests/test_a.py::test_x - AssertionError"}
            msg = str((action.get("arguments") or {}).get("message") or "")
            raise Submitted({"role": "exit", "content": msg,
                              "extra": {"exit_status": "Submitted", "submission": msg}})

    def _model(report):
        class _M:
            def __init__(self) -> None:
                self.turns = 0

            def format_message(self, **kwargs):
                return dict(kwargs)

            def query(self, messages):
                self.turns += 1
                if self.turns == 1:
                    return {"role": "assistant", "content": "", "extra": {"actions": [
                        {"tool": "edit", "id": "e1",
                         "arguments": {"path": "a.py", "old_string": "a", "new_string": "b"}}], "cost": 0.0}}
                if self.turns == 2:
                    return {"role": "assistant", "content": "", "extra": {"actions": [
                        {"tool": "bash", "id": "b1",
                         "arguments": {"command": "pytest -q tests/test_a.py"}}], "cost": 0.0}}
                # Reworded every turn — no dedupe can catch this.
                return {"role": "assistant", "content": "", "extra": {"actions": [
                    {"tool": "submit", "id": f"s{self.turns}",
                     "arguments": {"message": f"{report}\n<!-- {self.turns} -->"}}], "cost": 0.0}}

            def format_observation_messages(self, message, outputs, template_vars=None):
                return [{"role": "tool", "tool_call_id": "x",
                         "content": str([dict(o) for o in outputs])[:2000]}]

        return _M()

    # Keeps claiming success: the run must stop on the last retry, not spin to step_limit.
    model = _model(passing)
    agent = DefaultAgent(model, _Env(), verify_before_submit=True, step_limit=40,
                         interactive=False, approver=lambda *_a, **_k: "allow")
    result = agent.run("add a feature and test it")
    assert model.turns <= MAX_BLOCKED_SUBMITS + 2, f"looped {model.turns} turns"
    assert result.get("exit_status") == "Stalled"
    # The work and its gap stay visible instead of being thrown away.
    assert result.get("submission")
    assert (result.get("verification") or {}).get("gaps")

    # Switches to an honest report: accepted, and the run ends Submitted.
    model2 = _model(honest)
    agent2 = DefaultAgent(model2, _Env(), verify_before_submit=True, step_limit=40,
                          interactive=False, approver=lambda *_a, **_k: "allow")
    result2 = agent2.run("add a feature and test it")
    assert result2.get("exit_status") == "Submitted"
    assert model2.turns <= MAX_BLOCKED_SUBMITS + 2, f"looped {model2.turns} turns"


def test_no_action_nudges_exhaust_before_step_budget() -> None:
    from kite.agent.loop import _MAX_VERIFY_NUDGE_TURNS
    from kite.application.verification import MAX_BLOCKED_SUBMITS

    class NarratingModel(_TextOnlyModel):
        def __init__(self, next_action: bool) -> None:
            self.calls = 0
            self.next_action = next_action

        def query(self, messages):
            self.calls += 1
            content = "I'll inspect the failing test next." if self.next_action else "All tests pass. Task complete."
            return {"role": "assistant", "content": f"{content} (turn {self.calls})", "extra": {"actions": []}}

    cases = [
        ("next_action", "fix the module", _MAX_IDLE_TURNS),
        ("unverified_claim", "fix the module", _MAX_VERIFY_NUDGE_TURNS),
        ("casual_submit", "hi", MAX_BLOCKED_SUBMITS),
    ]
    for case, task, expected_calls in cases:
        model = NarratingModel(case == "next_action")
        events = []
        agent = DefaultAgent(model, _StubEnv(), interactive=True, step_limit=40, on_event=events.append)
        if case != "next_action":
            agent.verification.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
        result = agent.run(task)
        assert result["exit_status"] == "Stalled", case
        assert model.calls == expected_calls, case
        assert result["submission"].endswith(f"(turn {expected_calls})")
        if case == "casual_submit":
            assert sum(event.kind == "submit_blocked" for event in events) == MAX_BLOCKED_SUBMITS
            assert "exhausted its submission retries" in result["blocked_reason"]


def test_nested_go_verification_runs_from_module_root(tmp_path) -> None:
    from kite.application.verification import discover_workspace_profile

    module = tmp_path / "services" / "api"
    module.mkdir(parents=True)
    (module / "go.mod").write_text("module example.com/api\n\ngo 1.22\n", encoding="utf-8")
    profile = discover_workspace_profile(tmp_path)
    assert profile.scoped_test_command("services/api/main.go") == "cd services/api && go test ./..."



def test_plan_tools_and_dispatch_mode(workspace: Path) -> None:
    assert "write" not in PLAN_TOOLS and "edit" not in PLAN_TOOLS
    assert READONLY_TOOLS <= PLAN_TOOLS
    nested = tools_for_nested_subagent(["read", "grep", "subagent", "task", "bash", "memory"])
    assert "subagent" not in nested and "memory" not in nested
    enabled = ["read", "write", "edit", "bash", "todo_write", "grep", "task", "submit"]
    plan = tools_for_mode(AgentMode.PLAN, enabled)
    assert "write" not in plan and "submit" not in plan
    assert "submit" in tools_for_mode(AgentMode.BUILD, enabled)
    assert PARALLEL_SAFE_TOOLS.issubset(READONLY_TOOLS)
    assert is_parallel_safe("read") and is_parallel_safe("websearch") and is_parallel_safe("webfetch")
    assert not is_parallel_safe("write") and not is_parallel_safe("bash")
    from kite.agent.parallel import action_parallel_eligible, can_parallelize_batch

    assert action_parallel_eligible("write") and action_parallel_eligible("edit")
    cwd = str(workspace)
    assert can_parallelize_batch(
        [
            {"tool": "write", "arguments": {"path": "x.py", "content": "1"}},
            {"tool": "write", "arguments": {"path": "y.py", "content": "2"}},
        ],
        cwd=cwd,
    )
    assert {"write", "edit", "bash"} <= MUTATING_TOOLS
    from kite.guardrails import GuardrailConfig, GuardrailPolicy

    tools = make_coding_tools(cwd=str(workspace), guardrails=GuardrailPolicy(GuardrailConfig(), workspace), enabled=["bash"])
    plan_agent = DefaultAgent(object(), LocalEnvironment(registry=ToolRegistry(tools)), mode=AgentMode.PLAN)
    cmd = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    cmd_action = {"tool": "bash", "arguments": {"command": cmd}}
    out = plan_agent._invoke_tool("bash", {"command": cmd}, cmd_action)
    assert out.get("ok") is False
    submit = next(t for t in make_coding_tools(cwd=str(workspace), enabled=["submit"]) if t.name == "submit")
    assert not submit.run({}).get("ok")
    assert resolve_dispatch_mode({"prompt": "x", "background": True}) == (True, "explicit-async")
    assert resolve_dispatch_mode({"prompts": ["a", "b"], "labels": ["x", "y"]})[0] is False
    assert resolve_dispatch_mode({"prompt": "Survey routes in the background while I refactor the CLI."})[1] == "auto-async"
    assert resolve_dispatch_mode({"prompt": "Map the auth module and report back before continuing."})[1] == "auto-sync"
    assert resolve_dispatch_mode({"prompt": "Read the background jobs module under src/kite/tools"})[1] == "default-sync"


def test_steer_follow_up_and_compaction_events() -> None:
    queue = RunMessageQueue()
    queue.steer("focus on tests only")
    events: list[str] = []

    class _SteerModel(_StubModel):
        def __init__(self) -> None:
            self.calls = 0

        def query(self, messages):
            self.calls += 1
            if self.calls == 1:
                return {"role": "assistant", "content": "working", "extra": {"actions": [{"tool": "read", "arguments": {"path": "x"}}], "cost": 0.0}}
            return {"role": "assistant", "content": "done after steer", "extra": {"cost": 0.0}}

    model = _SteerModel()
    agent = DefaultAgent(model, LocalEnvironment(registry=ToolRegistry([])), step_limit=5, message_queue=queue, on_event=lambda e: events.append(e.kind))
    agent.messages = [model.format_message("system", content="sys"), model.format_message("user", content="ship it")]

    def _interrupt_mid_tool(*_a, **_k):
        agent.request_interrupt()
        return {"ok": True, "output": "file"}

    agent.env.execute = _interrupt_mid_tool  # type: ignore[method-assign]
    result = agent.run("ship it")
    assert result.get("exit_status") != "Interrupted"
    assert any("focus on tests only" in str(m.get("content") or "") for m in agent.messages if m.get("role") == "user")
    kinds: list[str] = []
    LoopCompactor(CompactionConfig(enabled=True, window=1000, compact_ratio=0.5), system="sys", on_event=lambda e: kinds.append(e.kind)).maybe_compact(
        [{"role": "system", "content": "x" * 400}, {"role": "user", "content": "y" * 400}, {"role": "assistant", "content": "z" * 400}],
        force=True,
    )
    assert "compaction_start" in kinds and "compaction_end" in kinds


def test_cancel_stops_running_bash(workspace: Path, monkeypatch) -> None:
    cancel = CancelToken()
    popen = subprocess.Popen
    processes = []
    argv = [sys.executable, "-c", "import threading; threading.Event().wait()"]
    command = subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)

    def cancel_after_spawn(*args, **kwargs):
        process = popen(*args, **kwargs)
        # Patching the shared subprocess module also intercepts Windows taskkill.
        if args[0] == command:
            processes.append(process)
            assert process.poll() is None
            cancel.request()
        return process

    monkeypatch.setattr("kite.tools.coding.subprocess.Popen", cancel_after_spawn)
    tools = make_coding_tools(cwd=str(workspace), cancel=cancel, enabled=["bash"], auto_venv=False)
    env = LocalEnvironment(registry=ToolRegistry(tools))
    # Cancel as soon as the real process exists, without racing a sleep timer.
    out = env.execute({"tool": "bash", "arguments": {"command": command}})
    assert out.get("cancelled") is True and out["ok"] is False
    assert len(processes) == 1 and processes[0].poll() is not None


def test_parallel_reads_preserve_every_result(workspace: Path) -> None:
    src = workspace / "src"
    (src / "b.py").write_text("y = 2\n", encoding="utf-8")
    model = MagicMock()
    model.format_observation_messages.return_value = [{"role": "user", "content": "ok"}]
    env = LocalEnvironment(cwd=str(workspace), registry=ToolRegistry(make_coding_tools(cwd=str(workspace), enabled=["read"])))
    agent = DefaultAgent(model, env, step_limit=5, cost_limit=1.0)
    agent.execute_actions(
        {
            "role": "assistant",
            "content": "",
            "extra": {"actions": [{"tool": "read", "arguments": {"path": str(src / "app.py")}}, {"tool": "read", "arguments": {"path": str(src / "b.py")}}]},
        }
    )
    outputs = model.format_observation_messages.call_args[0][1]
    assert len(outputs) == 2
    assert all(output["ok"] for output in outputs), outputs
    assert "x = 1" in outputs[0]["output"]
    assert "y = 2" in outputs[1]["output"]
    token = CancelToken()
    DefaultAgent(MagicMock(), MagicMock(), cancel=token).request_interrupt()
    assert token.is_set()


def test_harness_keeps_job_registry_after_run_error() -> None:
    from kite.agent.harness import Harness, HarnessConfig

    jobs = MagicMock()
    jobs.kill_all.return_value = 0

    class BoomRuntime:
        last_session = None
        job_registry = jobs
        cancel_token = None

        def run(self, task: str) -> dict:
            raise RuntimeError("boom")

    h = Harness(HarnessConfig())
    h._make_runtime = lambda: BoomRuntime()  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="boom"):
        h.run("task")
    assert h.job_registry is jobs
    assert h.teardown_jobs() == 0


def test_estimate_cost_from_usage_falls_back_to_price_map(monkeypatch) -> None:
    from kite.models.litellm_model import estimate_cost_from_usage

    litellm = ModuleType("litellm")
    litellm.model_cost = {
        "groq/llama-3.3-70b-versatile": {
            "input_cost_per_token": 0.00000059,
            "output_cost_per_token": 0.00000079,
            "cache_read_input_token_cost": 0.0000001,
        },
        "gpt-4o": {
            "input_cost_per_token": 0.0000025,
            "output_cost_per_token": 0.00001,
        },
    }
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    cost = estimate_cost_from_usage("groq/llama-3.3-70b-versatile", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.59 + 0.79)
    # Provider prefix is optional — prefixed names resolve via the bare id.
    assert estimate_cost_from_usage("openai/gpt-4o", 1_000_000, 0) == pytest.approx(2.5)
    cached = estimate_cost_from_usage(
        "groq/llama-3.3-70b-versatile", 1_000_000, 0, cache_read_tokens=500_000
    )
    assert cached == pytest.approx(500_000 * 0.00000059 + 500_000 * 0.0000001)
    assert estimate_cost_from_usage("unknown-model-xyz", 1000, 1000) == 0.0
    assert estimate_cost_from_usage("groq/llama-3.3-70b-versatile", 0, 0) == 0.0


def test_harness_config_rejects_unknown_fields() -> None:
    with pytest.raises(TypeError, match="unknown harness config"):
        build_harness_config(not_a_field=True)


def test_goal_persistence_and_recovery(kite_home) -> None:
    goal = SessionGoal(objective="Ship feature X", status="active")
    save_session_goal("sess-1", goal)
    assert load_session_goal("sess-1") == goal
    assert should_auto_recover(exit_status="ProviderFault", continues_used=0, goal_active=False)
    assert not should_auto_recover(exit_status="Interrupted", continues_used=0, goal_active=False)
    assert decide_recovery_continue(exit_status="LimitsExceeded", continues_used=0, max_continues=3, goal_active=True, todos=[{"status": "pending", "content": "fix tests"}], tool_call_count=1) == "continue"
    assert "Finish migration" in build_recovery_follow_up(exit_status="ProviderFault", continuity_markdown="## Continuity\n- Mission: x", goal_objective="Finish migration")

def test_after_tool_subagent_cost_and_worker_files() -> None:

    agent = DefaultAgent(_StubModel(), LocalEnvironment(registry=ToolRegistry([])))
    noted: list[str] = []

    class _Checkpoints:
        def record(self, path, label):  # noqa: ANN001
            noted.append(path)
            return None

    agent.checkpoints = _Checkpoints()
    agent._emit_commit = lambda *_a, **_k: None
    out = {
        "ok": True,
        "output": "crew report",
        "total_cost": 0.25,
        "files_touched": ["w/a.py"],
        "results": [{"files_touched": ["w/b.py"]}, {"ok": False}],
    }
    agent._after_tool("subagent", {}, {}, out, 5, [])
    assert agent.cost == pytest.approx(0.25)
    assert noted == ["w/a.py", "w/b.py"]


