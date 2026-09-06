"""Guardrail and sandbox behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.config import GuardrailConfig
from kite.guardrails import GuardrailPolicy
from kite.guardrails.sandbox import (
    check_dangerous,
    cwd_in_trusted,
    is_benign_cache_delete,
    workspace_root,
)


def test_blocks_dangerous_bash() -> None:
    assert check_dangerous("rm -rf /")
    assert not check_dangerous("ls -la")
    assert check_dangerous("git push origin main")
    assert check_dangerous("git push --force")
    assert not check_dangerous("git status")
    assert not check_dangerous("git commit -m 'ok'")


def test_relative_cache_deletes_not_hard_blocked() -> None:
    for cmd in (
        "rmdir /s /q .pytest_cache",
        r"rmdir /s /q .\.pytest_cache",
        'powershell -Command "Remove-Item -Recurse -Force .pytest_cache"',
        "Remove-Item -Recurse -Force .ruff_cache",
        "rm -rf .pytest_cache .ruff_cache",
    ):
        assert not check_dangerous(cmd), cmd
        assert is_benign_cache_delete(cmd), cmd


def test_absolute_recursive_deletes_still_hard_blocked() -> None:
    assert check_dangerous(r"rmdir /s /q C:\Windows\Temp")
    assert check_dangerous(r'Remove-Item -Recurse -Force C:\Users')
    assert check_dangerous("rmdir /s /q /etc")
    assert not is_benign_cache_delete(r"rmdir /s /q C:\Windows\Temp")
    assert not is_benign_cache_delete("rm -rf src")


def test_guardrail_policy_allows_relative_cache_delete(workspace: Path) -> None:
    policy = GuardrailPolicy(GuardrailConfig(), workspace)
    v = policy.check_bash(r'powershell -Command "Remove-Item -Recurse -Force .pytest_cache"')
    assert v.allowed, v.reason
    v2 = policy.check_bash("rmdir /s /q .ruff_cache")
    assert v2.allowed, v2.reason


def test_cwd_in_trusted_subtree(workspace: Path) -> None:
    root = workspace_root(workspace)
    src = workspace / "src"
    assert cwd_in_trusted(src, root, ["src/"])
    assert not cwd_in_trusted(workspace, root, ["src/"])


def test_restricted_read_allows_global_skill_tree(workspace: Path, kite_home: Path, tmp_path: Path) -> None:
    from kite.guardrails.sandbox import is_user_skill_read

    real = tmp_path / "skill-src"
    real.mkdir()
    (real / "notes.md").write_text("ok\n", encoding="utf-8")
    link = kite_home / "skills" / "linked-skill"
    link.parent.mkdir(parents=True, exist_ok=True)
    from kite.skills.install import symlink_or_copy

    if symlink_or_copy(link, real) != "link":
        pytest.skip("symlinks not permitted on this OS")
    policy = GuardrailPolicy(GuardrailConfig(execution_mode="restricted"), workspace)
    via_home = policy.check_path(str(link / "notes.md"))
    assert via_home.allowed
    via_target = policy.check_path(str(real / "notes.md"))
    assert via_target.allowed
    assert is_user_skill_read(real / "notes.md")
    write = policy.check_path(str(real / "notes.md"), for_write=True)
    assert not write.allowed


def test_path_escape_blocked_in_restricted_mode(workspace: Path, tmp_path: Path) -> None:
    external = tmp_path / "outside.txt"
    external.write_text("secret\n", encoding="utf-8")
    policy = GuardrailPolicy(GuardrailConfig(execution_mode="restricted"), workspace)
    verdict = policy.check_path(str(external))
    assert not verdict.allowed
    assert "sandbox" in verdict.reason.lower() or "escape" in verdict.reason.lower()


def test_write_inside_workspace_allowed(workspace: Path) -> None:
    policy = GuardrailPolicy(GuardrailConfig(), workspace)
    target = workspace / "src" / "new.py"
    verdict = policy.check_path(str(target), for_write=True)
    assert verdict.allowed


def test_redact_secrets_masks_api_keys(workspace: Path) -> None:
    policy = GuardrailPolicy(GuardrailConfig(), workspace)
    text = "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"
    redacted, count = policy.redact_secrets(text)
    assert count >= 1
    assert "REDACTED" in redacted
    assert "sk-abc" not in redacted


def test_blocks_env_dump_commands(workspace: Path) -> None:
    policy = GuardrailPolicy(GuardrailConfig(), workspace)
    for cmd in ("env", "printenv", "export", "set", "Get-ChildItem Env:", "dir env:"):
        verdict = policy.check_bash(cmd)
        assert not verdict.allowed, cmd
        assert "environment" in verdict.reason.lower()
    assert policy.check_bash("echo hello").allowed
    assert policy.check_bash("npm test").allowed
