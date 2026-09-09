"""Incremental security hardening — meta redaction, gh env, SSRF userinfo, attach guard."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from kite.config.user import UserConfig
from kite.guardrails.ssrf import url_blocked
from kite.memory.session import SessionMeta, create_session, format_meta_line
from kite.tools.github import _run_gh
from kite.ui.approval import ApprovalPolicy
from kite.ui.attach import load_file


def test_meta_line_redacts_task_secrets(kite_home) -> None:
    meta = SessionMeta(
        id="s1",
        created_at=1_700_000_000.0,
        updated_at=1_700_000_000.0,
        cwd="/tmp",
        provider="p",
        model="m",
        task="use Bearer SECRETTOKEN please",
    )
    line = format_meta_line(meta)
    assert "SECRETTOKEN" not in line
    assert "[REDACTED]" in line


def test_blocks_url_with_embedded_credentials() -> None:
    assert url_blocked("http://user:pass@example.com/path") == "URLs with credentials blocked"


def test_attach_refuses_protected_env_file(tmp_path) -> None:
    secret = tmp_path / ".env"
    secret.write_text("API_KEY=abc\n", encoding="utf-8")
    with pytest.raises(ValueError, match="protected path"):
        load_file(secret)


def test_gh_subprocess_uses_filtered_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    captured: dict = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("kite.tools.github._gh_available", lambda: True)
    _run_gh(["version"])
    env = captured.get("env") or {}
    assert "GITHUB_TOKEN" not in env


@pytest.mark.skipif(sys.platform == "win32", reason="Unix owner-only file permissions")
def test_config_and_approvals_saved_owner_only(kite_home) -> None:
    cfg = UserConfig.load()
    cfg.default_provider = "groq"
    path = cfg.save()
    assert path.stat().st_mode & 0o077 == 0

    policy = ApprovalPolicy(always_patterns={"bash:*"})
    policy.save()
    approvals = kite_home / "approvals.json"
    assert approvals.is_file()
    assert approvals.stat().st_mode & 0o077 == 0


def test_session_meta_row_json_parseable(kite_home) -> None:
    session = create_session(
        task="Bearer META-SECRET",
        cwd="/tmp",
        provider="p",
        model="m",
    )
    line = session.path.read_text(encoding="utf-8").splitlines()[0]
    row = json.loads(line)
    assert row["type"] == "meta"
    assert "META-SECRET" not in line
