"""Tests for child-process env filtering and chained env-dump guardrails."""

from __future__ import annotations

from kite.guardrails import env_dump_blocked
from kite.guardrails.env_filter import filtered_child_env, is_sensitive_env_key


def test_is_sensitive_env_key() -> None:
    assert is_sensitive_env_key("OPENAI_API_KEY")
    assert is_sensitive_env_key("GITHUB_TOKEN")
    assert is_sensitive_env_key("AZURE_OPENAI_API_KEY")
    assert not is_sensitive_env_key("PATH")
    assert not is_sensitive_env_key("HOME")


def test_filtered_child_env_strips_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = filtered_child_env({"PAGER": "cat"})
    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["PAGER"] == "cat"


def test_env_dump_blocked_on_chained_commands() -> None:
    assert env_dump_blocked("echo hi && env")
    assert env_dump_blocked("printenv | cat")
    assert env_dump_blocked("Get-ChildItem Env: | Out-String")
    assert not env_dump_blocked("echo hello && npm test")
