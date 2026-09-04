"""Repo map and SOTA harness feature tests."""

from __future__ import annotations

from pathlib import Path

from kite.agent.mode import BUILD_TOOLS, tools_for_mode, AgentMode
from kite.agent.verification import VerificationCollector
from kite.application.tools.contracts import ToolResult
from kite.context.repomap import build_repo_map
from kite.eval import ReplayBundle, run_replay
from kite.tools.coding import make_coding_tools


def test_build_repo_map_finds_python_symbols(workspace: Path) -> None:
    src = workspace / "src" / "demo"
    src.mkdir(parents=True)
    (src / "main.py").write_text(
        "class Widget:\n    pass\n\ndef run():\n    return 1\n",
        encoding="utf-8",
    )
    text = build_repo_map(workspace, max_files=10)
    assert "main.py" in text
    assert "Widget" in text or "run" in text


def test_submit_tool_registered_and_raises_submitted(workspace: Path) -> None:
    from kite.agent.exceptions import Submitted
    from kite.env.local import LocalEnvironment

    tools = make_coding_tools(cwd=str(workspace), enabled=["submit"])
    names = [t.name for t in tools]
    assert "submit" in names
    env = LocalEnvironment(cwd=str(workspace), registry=__import__("kite.tools", fromlist=["ToolRegistry"]).ToolRegistry(tools))
    try:
        env.execute({"tool": "submit", "arguments": {"message": "## Done\n- shipped"}})
        raise AssertionError("expected Submitted")
    except Submitted as exc:
        assert "shipped" in str(exc.messages[0].get("content") or "")


def test_submit_tool_requires_message(workspace: Path) -> None:
    tools = make_coding_tools(cwd=str(workspace), enabled=["submit"])
    submit = next(t for t in tools if t.name == "submit")
    out = submit.run({})
    assert not out.get("ok")
    assert "message required" in str(out.get("error") or "")


def test_submit_in_build_tools() -> None:
    enabled = [
        "bash", "read", "write", "edit", "grep", "glob", "ls", "submit",
        "todo_write", "todo_read", "task",
    ]
    build = tools_for_mode(AgentMode.BUILD, enabled)
    assert "submit" in build
    assert "submit" not in tools_for_mode(AgentMode.PLAN, enabled)


def test_verification_collector_evidence_in_summary() -> None:
    vc = VerificationCollector(workspace_root="/tmp", run_id="run-ev")
    vc.on_tool_end(
        "bash",
        {"command": "pytest -q"},
        {"ok": True, "returncode": 0, "output": "3 passed"},
    )
    summary = vc.summary()
    assert summary.get("evidence", {}).get("status") == "verified"
    assert summary["evidence"]["passed"] >= 1


def test_replay_acceptance_checks() -> None:
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
        acceptance={
            "content_contains": "html updated",
            "content_excludes": "pytest",
            "min_events": 1,
            "event_kinds": ["verification_status"],
        },
    )
    out = run_replay(bundle)
    assert out["ok"]
    assert out["acceptance"]["ok"]


def test_replay_acceptance_failure() -> None:
    bundle = ReplayBundle(
        run_id="acc-2",
        prompt_hash="h",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "nope"}],
        acceptance={"content_contains": "expected phrase"},
    )
    out = run_replay(bundle)
    assert not out["ok"]
    assert out["acceptance"]["failures"]
