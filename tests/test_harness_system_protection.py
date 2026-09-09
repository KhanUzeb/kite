"""Harness-wide protection against OS/software/hardware interference."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kite.application.policy import PolicyEngine
from kite.application.tools import ToolCall
from kite.config import GuardrailConfig
from kite.guardrails import GuardrailPolicy
from kite.guardrails.sandbox import check_dangerous, is_os_interface_path, is_protected
from kite.tools.coding import make_coding_tools


def test_blocks_privileged_and_container_bash() -> None:
    assert check_dangerous("sudo rm -rf /")
    assert check_dangerous("docker run -it ubuntu bash")
    assert check_dangerous("kubectl apply -f deploy.yaml")
    assert check_dangerous("mount /dev/sda1 /mnt")
    assert check_dangerous("echo x > /dev/sda")
    assert not check_dangerous("docker --version")


@pytest.mark.skipif(sys.platform == "win32", reason="Unix proc/sys/dev paths")
def test_os_interface_paths_protected() -> None:
    assert is_os_interface_path(Path("/proc/self/environ"))
    assert is_os_interface_path(Path("/sys/class/net"))
    assert is_os_interface_path(Path("/dev/sda"))
    assert is_protected(Path("/proc/1/cmdline"))
    assert not is_os_interface_path(Path("/tmp/project/proc-notes.txt"))


def test_guardrail_blocks_os_interface_bash(workspace: Path) -> None:
    policy = GuardrailPolicy(GuardrailConfig(), workspace)
    verdict = policy.check_bash("cat /proc/self/environ")
    assert not verdict.allowed
    assert "OS interface" in verdict.reason


def test_guardrail_blocks_localhost_webfetch(workspace: Path) -> None:
    policy = GuardrailPolicy(GuardrailConfig(), workspace)
    verdict = policy.check_tool_call("webfetch", {"url": "http://127.0.0.1/admin"})
    assert not verdict.allowed
    assert "private" in verdict.reason.lower() or "blocked" in verdict.reason.lower()


def test_policy_blocks_webfetch_in_restricted_mode(workspace: Path) -> None:
    engine = PolicyEngine(workspace, execution_mode="restricted")
    call = ToolCall(call_id="1", name="webfetch", arguments={"url": "https://example.com"})
    intent = engine.derive_intent(call)
    decision = engine.authorize(intent)
    assert not decision.allowed
    assert "network" in decision.reason.lower()


def test_policy_blocks_websearch_in_restricted_mode(workspace: Path) -> None:
    engine = PolicyEngine(workspace, execution_mode="restricted")
    call = ToolCall(call_id="2", name="websearch", arguments={"query": "kite agent"})
    intent = engine.derive_intent(call)
    decision = engine.authorize(intent)
    assert not decision.allowed


def test_grep_rg_uses_filtered_child_env(workspace: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-key-value")
    captured: dict = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/rg" if name == "rg" else None)

    tools = make_coding_tools(cwd=str(workspace), enabled=["grep"])
    grep_tool = next(t for t in tools if t.name == "grep")
    grep_tool.run({"pattern": "foo", "path": "."})

    env = captured.get("env") or {}
    assert "OPENAI_API_KEY" not in env


@pytest.mark.skipif(not os.path.exists("/proc"), reason="/proc not present")
def test_proc_in_protected_roots() -> None:
    from kite.guardrails.sandbox import protected_roots

    roots = {str(p) for p in protected_roots()}
    assert "/proc" in roots or any(r.endswith("/proc") for r in roots)
