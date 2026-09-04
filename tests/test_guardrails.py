"""Guardrail and sandbox behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.config import GuardrailConfig
from kite.guardrails import GuardrailPolicy
from kite.guardrails.sandbox import check_dangerous, cwd_in_trusted, workspace_root


def test_blocks_dangerous_bash() -> None:
    assert check_dangerous("rm -rf /")
    assert not check_dangerous("ls -la")
    assert check_dangerous("git push origin main")
    assert check_dangerous("git push --force")
    assert not check_dangerous("git status")
    assert not check_dangerous("git commit -m 'ok'")


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
