"""Agent loop, modes, completion, cancel, dispatch, recovery, submit gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kite.agent.cancel import CancelToken
from kite.agent.compaction import CompactionConfig, LoopCompactor
from kite.agent.dispatch_mode import dispatch_hint, resolve_dispatch_mode
from kite.agent.exceptions import LimitsExceeded, ProviderFault, Submitted
from kite.agent.harness_build import build_harness_config
from kite.agent.loop import _MAX_IDLE_TURNS, DefaultAgent, _allow_text_submit
from kite.agent.loop_guard import LoopGuard
from kite.agent.mode import (
    MUTATING_TOOLS,
    PARALLEL_SAFE_TOOLS,
    PLAN_TOOLS,
    READONLY_TOOLS,
    AgentMode,
    tools_for_mode,
    tools_for_nested_subagent,
)
from kite.agent.queue import RunMessageQueue
from kite.agent.verification import VerificationCollector
from kite.env.local import LocalEnvironment
from kite.memory.goal import SessionGoal, format_goal_section, load_session_goal, save_session_goal
from kite.memory.recovery import build_recovery_follow_up, decide_recovery_continue, should_auto_recover
from kite.memory.session import load_session_todos, persist_session_todos
from kite.prompts import load_prompt_template
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


def test_query_limits_retry_and_fault() -> None:
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


def test_loop_guard_warns_and_hard_stops() -> None:
    guard = LoopGuard(repeat_threshold=3)
    args = {"command": "ls"}
    assert guard.record("bash", args).warning is None
    warning = guard.record("bash", args)
    assert warning.warning and "same arguments" in warning.warning
    grep = LoopGuard(repeat_threshold=3)
    assert grep.record("grep", {"pattern": "foo"}).warning is None
    assert grep.record("grep", {"pattern": "foo"}).warning is None
    assert grep.record("grep", {"pattern": "foo"}).warning is not None
    progress = LoopGuard(repeat_threshold=3, hard_threshold=5)
    pending = {"command": "curl -s localhost/status"}
    progress.record("bash", pending, {"ok": True, "output": "pending"})
    progress.record("bash", pending, {"ok": True, "output": "pending"})
    assert progress.record("bash", pending, {"ok": True, "output": "ready"}).warning is None
    hard = LoopGuard(repeat_threshold=2, hard_threshold=4)
    for _ in range(3):
        hard.record("bash", args, {"ok": True, "output": "same"})
    assert hard.record("bash", args, {"ok": True, "output": "same"}).hard_stop


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
    from kite.agent.hooks import HookBus
    from kite.agent.runtime import AgentRuntime, RuntimeOptions

    fired: list[str] = []
    runtime = AgentRuntime(RuntimeOptions(cwd="."), hooks=HookBus())
    runtime.hooks.on("after_prepare", lambda **_: fired.append("yes"))
    from unittest.mock import patch

    with patch("kite.agent.runtime.resolve_model", return_value=MagicMock(provider="test", model="m", context_window=128000)):
        with patch("kite.providers.resolve.missing_credentials", return_value=None):
            with patch("kite.providers.resolve.missing_model", return_value=None):
                runtime.prepare()
    assert fired == ["yes"]


def test_plan_build_tools_and_plan_submit_block(workspace: Path) -> None:
    assert "write" not in PLAN_TOOLS and "edit" not in PLAN_TOOLS
    assert READONLY_TOOLS <= PLAN_TOOLS
    nested = tools_for_nested_subagent(["read", "grep", "subagent", "task", "bash", "memory"])
    assert "subagent" not in nested and "memory" not in nested
    enabled = ["read", "write", "edit", "bash", "todo_write", "grep", "task", "submit"]
    plan = tools_for_mode(AgentMode.PLAN, enabled)
    assert "write" not in plan and "submit" not in plan
    assert "submit" in tools_for_mode(AgentMode.BUILD, enabled)
    assert PARALLEL_SAFE_TOOLS.issubset(READONLY_TOOLS)
    assert {"write", "edit", "bash"} <= MUTATING_TOOLS
    assert "Checklist handoff" in load_prompt_template("mode_build")
    plan_prompt = load_prompt_template("mode_plan")
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in plan_prompt
    from kite.guardrails import GuardrailConfig, GuardrailPolicy

    tools = make_coding_tools(cwd=str(workspace), guardrails=GuardrailPolicy(GuardrailConfig(), workspace), enabled=["bash"])
    agent = DefaultAgent(object(), LocalEnvironment(registry=ToolRegistry(tools)), mode=AgentMode.PLAN)
    cmd = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    cmd_action = {"tool": "bash", "arguments": {"command": cmd}}
    out = agent._invoke_tool("bash", {"command": cmd}, cmd_action)
    assert out.get("ok") is False
    submit = next(t for t in make_coding_tools(cwd=str(workspace), enabled=["submit"]) if t.name == "submit")
    assert not submit.run({}).get("ok")


def test_completion_idle_and_error_stop(monkeypatch) -> None:
    assert not _allow_text_submit("I finished the refactor.", mode=AgentMode.BUILD, interactive=True)
    assert _allow_text_submit("Hey! 👋", mode=AgentMode.BUILD, interactive=True, last_user="hi")
    agent = DefaultAgent(_TextOnlyModel(), _StubEnv(), interactive=True, mode=AgentMode.BUILD, provider_max_retries=1)
    agent.messages = [{"role": "user", "content": "run the test suite"}]
    agent.execute_actions({"role": "assistant", "content": "All tests pass. Task complete.", "extra": {"actions": []}})
    blob = "\n".join(str(m.get("content") or "") for m in agent.messages)
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

    class _Boom:
        def format_message(self, **kwargs):
            return dict(kwargs)

        def query(self, messages):
            raise RuntimeError("provider exploded")

        def format_observation_messages(self, message, outputs, template_vars=None):
            return []

    boom = DefaultAgent(_Boom(), _StubEnv(), interactive=False, mode=AgentMode.BUILD, provider_max_retries=1)
    monkeypatch.setattr("kite.models.retry.is_transient_provider_error", lambda _e: False)
    result = boom.run("do something")
    assert result.get("exit_status") == "Error"


def test_cancel_parallel_reads_and_interrupt(workspace: Path) -> None:
    import threading
    import time

    cancel = CancelToken()
    tools = make_coding_tools(cwd=str(workspace), cancel=cancel, enabled=["bash"], timeout=30)
    env = LocalEnvironment(registry=ToolRegistry(tools))
    threading.Thread(target=lambda: (time.sleep(0.3), cancel.request()), daemon=True).start()
    out = env.execute({"tool": "bash", "arguments": {"command": "sleep 5 && echo done"}})
    assert out.get("cancelled") is True and out["ok"] is False
    src = workspace / "src"
    (src / "b.py").write_text("y = 2\n", encoding="utf-8")
    model = MagicMock()
    model.format_observation_messages.return_value = [{"role": "user", "content": "ok"}]
    agent = DefaultAgent(model, LocalEnvironment(registry=ToolRegistry(make_coding_tools(cwd=str(workspace), enabled=["read"]))), step_limit=5, cost_limit=1.0)
    agent.execute_actions(
        {
            "role": "assistant",
            "content": "",
            "extra": {"actions": [{"tool": "read", "arguments": {"path": str(src / "app.py")}}, {"tool": "read", "arguments": {"path": str(src / "b.py")}}]},
        }
    )
    assert len(model.format_observation_messages.call_args[0][1]) == 2
    token = CancelToken()
    DefaultAgent(MagicMock(), MagicMock(), cancel=token).request_interrupt()
    assert token.is_set()


def test_dispatch_mode_inference() -> None:
    assert resolve_dispatch_mode({"prompt": "x", "background": True}) == (True, "explicit-async")
    assert resolve_dispatch_mode({"prompts": ["a", "b"], "labels": ["x", "y"]})[0] is False
    assert resolve_dispatch_mode({"prompt": "Survey routes in the background while I refactor the CLI."})[1] == "auto-async"
    assert resolve_dispatch_mode({"prompt": "Map the auth module and report back before continuing."})[1] == "auto-sync"
    assert resolve_dispatch_mode({"prompt": "Read the background jobs module under src/kite/tools"})[1] == "default-sync"
    assert "async" in dispatch_hint("auto-async")


def test_harness_build_and_recovery(kite_home, workspace: Path) -> None:
    cfg = build_harness_config()
    assert cfg.mode == "build" and cfg.memory_in_prompt is False
    shaped = build_harness_config(provider="groq", interactive=True, memory_in_prompt=True, reasoning="fast")
    assert shaped.interactive and shaped.reasoning == "fast"
    with pytest.raises(TypeError, match="unknown harness config"):
        build_harness_config(not_a_field=True)
    save_session_goal("sess-1", SessionGoal(objective="Ship feature X", status="active"))
    assert load_session_goal("sess-1") is not None
    assert "Keep tests green" in format_goal_section("Keep tests green")
    assert should_auto_recover(exit_status="ProviderFault", continues_used=0, goal_active=False)
    assert not should_auto_recover(exit_status="Interrupted", continues_used=0, goal_active=False)
    assert decide_recovery_continue(exit_status="LimitsExceeded", continues_used=0, max_continues=3, goal_active=True, todos=[{"status": "pending", "content": "fix tests"}], tool_call_count=1) == "continue"
    assert "Finish migration" in build_recovery_follow_up(exit_status="ProviderFault", continuity_markdown="## Continuity\n- Mission: x", goal_objective="Finish migration")
    from kite.memory.session import create_session

    session = create_session(task="demo", cwd=str(workspace), provider="groq", model="test")
    persist_session_todos(session.id, [{"id": "1", "content": "run pytest", "status": "pending"}])
    assert load_session_todos(session.id)[0]["content"] == "run pytest"
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["resume", "--last", "--retry", "abc12345"])
    assert args.retry is True and args.session == "abc12345"


def test_submit_gate_and_executor_approval(workspace: Path) -> None:
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
    assert blocked.get("blocked") or not blocked.get("ok")
    denied = DefaultAgent(MagicMock(), MagicMock(), tool_executor=None)._run_gated("write", {"path": "outside.txt", "content": "x"}, {})
    assert denied.get("blocked") is True
    inspect = DefaultAgent(MagicMock(), MagicMock(), tool_executor=build_tool_executor(workspace_root=workspace, execution_mode="host", no_guardrails=False, runner=lambda call: {"ok": True, "output": "clean"}), mode=AgentMode.PLAN)
    assert inspect._run_gated_via_executor(
        "bash",
        {"command": "git status"},
        {"tool": "bash", "arguments": {"command": "git status"}},
    ).get("ok") is True


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
