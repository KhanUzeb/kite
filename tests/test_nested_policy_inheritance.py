"""Nested agent policy inheritance tests."""

from __future__ import annotations

from kite.application.policy import child_inherits_parent_policy


def test_nested_inherits_workspace_mode_and_guardrails() -> None:
    inherited = child_inherits_parent_policy(
        parent_approval="approve",
        parent_mode="plan",
        parent_no_guardrails=False,
        parent_execution_mode="restricted",
    )
    assert inherited["approval"] == "approve"
    assert inherited["mode"] == "plan"
    assert inherited["no_guardrails"] is False
    assert inherited["execution_mode"] == "restricted"


def test_nested_rejects_guardrail_disable_attempt() -> None:
    inherited = child_inherits_parent_policy(
        parent_approval="auto",
        parent_mode="build",
        parent_no_guardrails=False,
        parent_execution_mode="host",
        child_overrides={"no_guardrails": True, "approval": "yolo"},
    )
    assert inherited["no_guardrails"] is False
    assert inherited["approval"] == "auto"
