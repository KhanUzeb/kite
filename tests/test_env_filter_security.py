"""Environment filtering — prevent secret re-injection via extra."""

from __future__ import annotations

import pytest

from kite.guardrails.env_filter import (
    SensitiveEnvInjectionError,
    filtered_child_env,
    is_sensitive_env_key,
)


def test_is_sensitive_env_key() -> None:
    assert is_sensitive_env_key("OPENAI_API_KEY")
    assert is_sensitive_env_key("GITHUB_TOKEN")
    assert not is_sensitive_env_key("PAGER")


def test_parent_sensitive_keys_stripped(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    monkeypatch.setenv("PAGER", "less")
    env = filtered_child_env()
    assert "OPENAI_API_KEY" not in env
    assert env.get("PAGER") == "less"


def test_extra_cannot_reinject_sensitive_keys(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = filtered_child_env(
        {
            "ANTHROPIC_API_KEY": "injected",
            "PAGER": "cat",
            "SAFE_VAR": "ok",
        }
    )
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PAGER"] == "cat"
    assert env["SAFE_VAR"] == "ok"


def test_strict_mode_raises_on_sensitive_extra() -> None:
    with pytest.raises(SensitiveEnvInjectionError) as exc:
        filtered_child_env({"GITHUB_TOKEN": "nope"}, strict=True)
    assert "GITHUB_TOKEN" in exc.value.keys


def test_prepare_child_env_uses_policy(monkeypatch, tmp_path) -> None:
    from kite.env.venv import prepare_child_env

    monkeypatch.setenv("XAI_API_KEY", "secret")
    env = prepare_child_env(cwd=tmp_path, extra={"XAI_API_KEY": "also-secret", "PAGER": "cat"})
    assert "XAI_API_KEY" not in env
    assert env.get("PAGER") == "cat"
