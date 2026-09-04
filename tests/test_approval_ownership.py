"""Approval ownership and nested policy inheritance tests."""

from __future__ import annotations

import threading
import time

from kite.application.policy import ApprovalCoordinator, child_inherits_parent_policy
from kite.application.tools.effects import tool_requires_approval_gate


def test_memory_remember_requires_approval_gate() -> None:
    assert tool_requires_approval_gate("memory", {"action": "remember", "text": "x"})


def test_skill_install_requires_approval_gate() -> None:
    assert tool_requires_approval_gate("skill", {"install": "pkg"})


def test_child_cannot_elevate_to_yolo() -> None:
    inherited = child_inherits_parent_policy(
        parent_approval="approve",
        parent_mode="build",
        parent_no_guardrails=False,
        parent_execution_mode="restricted",
        child_overrides={"approval": "yolo"},
    )
    assert inherited["approval"] == "approve"


def test_child_cannot_enable_guardrails_off_when_parent_disallows() -> None:
    inherited = child_inherits_parent_policy(
        parent_approval="auto",
        parent_mode="build",
        parent_no_guardrails=False,
        parent_execution_mode="restricted",
        child_overrides={"no_guardrails": True},
    )
    assert inherited["no_guardrails"] is False


def test_approval_coordinator_blocks_until_resolve() -> None:
    coord = ApprovalCoordinator(interactive=True)
    results: list[str] = []

    def worker() -> None:
        results.append(
            coord.request("bash", {"command": "rm x"}, reason="destructive", mandatory=True)
        )

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


def test_non_interactive_mandatory_denies_immediately() -> None:
    coord = ApprovalCoordinator(interactive=False)
    decision = coord.request("bash", {"command": "curl x"}, mandatory=True)
    assert decision == "deny"
