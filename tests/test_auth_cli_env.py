"""Provider-CLI subprocess hygiene: sanitized env + console isolation.

Regression locks for the "terminal title becomes `claude`" bug. A delegated
provider CLI (claude, agy, grok) must never inherit the parent agent's
session identity, and on Windows must never be able to drive the user's console.
Both guards live in ``kite.providers.auth.cli`` and are asserted here for
*every* spawn helper — ``run_cli``, ``run_checked`` and ``run_cli_streaming``.

The real ``claude`` binary is never executed: ``subprocess.run`` /
``subprocess.Popen`` are replaced with recorders that capture the exact kwargs
each helper hands down.
"""

from __future__ import annotations

import io
import subprocess
import sys
from typing import Any

import pytest

from kite.providers.auth import cli as cli_mod
from kite.providers.auth.cli import (
    console_isolation_kwargs,
    provider_cli_env,
    run_checked,
    run_cli,
    run_cli_streaming,
)

# Credential / home vars the other delegated logins depend on. None of these
# carry a CLAUDE/ANTHROPIC prefix, so sanitization must leave every one intact:
# grok reads GROK_HOME, xAI materialization reads XAI_OAUTH_TOKEN_DIR, codex
# materialization reads CHATGPT_TOKEN_DIR, and agy/Gemini ride GOOGLE_*.
_FOREIGN_CHILD_VARS = (
    "GROK_HOME",
    "XAI_OAUTH_TOKEN_DIR",
    "XAI_OAUTH_API_BASE",
    "CHATGPT_TOKEN_DIR",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "AGY_API_KEY",
    "AGY_HOME",
)


class _FakePopen:
    """Minimal stand-in for ``subprocess.Popen`` (no process is ever created)."""

    def __init__(self, argv: list[str], *, stdout: str = "", returncode: int = 0) -> None:
        self.args = argv
        self.returncode = returncode
        self.stdout = io.StringIO(stdout)
        self.stdin = None
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002 - signature parity
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _record_run(monkeypatch: pytest.MonkeyPatch, **result: Any) -> dict[str, Any]:
    """Replace subprocess.run with a recorder; return the captured-kwargs box."""
    seen: dict[str, Any] = {}

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = list(argv)
        seen.update(kwargs)
        return subprocess.CompletedProcess(
            list(argv), result.get("returncode", 0), result.get("stdout", ""), ""
        )

    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run)
    return seen


def _record_popen(
    monkeypatch: pytest.MonkeyPatch, *, stdout: str = "line one\n", returncode: int = 0
) -> dict[str, Any]:
    """Replace subprocess.Popen with a recorder; return the captured-kwargs box."""
    seen: dict[str, Any] = {}

    def _fake_popen(argv: list[str], **kwargs: Any) -> _FakePopen:
        seen["argv"] = list(argv)
        seen.update(kwargs)
        return _FakePopen(list(argv), stdout=stdout, returncode=returncode)

    monkeypatch.setattr(cli_mod.subprocess, "Popen", _fake_popen)
    return seen


def _force_platform(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(cli_mod.sys, "platform", platform)


def _c_test_run_cli_strips_session_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE_*/ANTHROPIC_* never reach a delegated child, in any letter case."""
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "12345")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-lite-llm-routing-key")
    monkeypatch.setenv("Anthropic_Custom_Header", "lower-case-prefix-match")
    seen = _record_run(monkeypatch, stdout="{}")

    proc = run_cli("claude", "auth", "status", "--json", timeout=15.0)

    assert proc.returncode == 0
    assert seen["argv"] == ["claude", "auth", "status", "--json"]
    child_env = seen["env"]
    assert "CLAUDE_CODE_SSE_PORT" not in child_env
    assert "ANTHROPIC_API_KEY" not in child_env
    assert "Anthropic_Custom_Header" not in child_env
    assert all("sk-ant-lite-llm-routing-key" not in v for v in child_env.values())


def _c_test_run_cli_preserves_what_a_child_login_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip too much and every login breaks: PATH, HOME, KITE_HOME, foreign creds stay."""
    monkeypatch.setenv("PATH", os_ish_path := "C:\\bin")
    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\tester")
    monkeypatch.setenv("KITE_HOME", "C:\\Users\\tester\\.kite")
    monkeypatch.setenv("KITE_OFFLINE", "1")
    for var in _FOREIGN_CHILD_VARS:
        monkeypatch.setenv(var, f"value-for-{var}")
    # A non-Anthropic credential a child genuinely routes on.
    monkeypatch.setenv("GROQ_API_KEY", "gsk-not-anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-be-dropped")
    seen = _record_run(monkeypatch)

    run_cli("claude", "auth", "status")

    child_env = seen["env"]
    assert child_env["PATH"] == os_ish_path
    assert child_env["HOME"] == "/home/tester"
    assert child_env["USERPROFILE"] == "C:\\Users\\tester"
    assert child_env["KITE_HOME"] == "C:\\Users\\tester\\.kite"
    assert child_env["KITE_OFFLINE"] == "1"
    assert child_env["GROQ_API_KEY"] == "gsk-not-anthropic"
    for var in _FOREIGN_CHILD_VARS:
        assert child_env[var] == f"value-for-{var}", var
    assert "ANTHROPIC_API_KEY" not in child_env


def _c_test_run_cli_streaming_sanitizes_env_and_isolates_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GAP 1 lock: the OAuth-login path needs BOTH guards, not just the env."""
    _force_platform(monkeypatch, "win32")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-lite-llm-routing-key")
    monkeypatch.setenv("GROK_HOME", "C:\\Users\\tester\\.grok")
    monkeypatch.setenv("PATH", "C:\\bin")
    seen = _record_popen(monkeypatch, stdout="Open https://auth.x.ai/oauth2/authorize\n")

    seen_lines: list[str] = []
    proc = run_cli_streaming("grok", "login", on_line=seen_lines.append, timeout=30.0)

    assert proc.returncode == 0
    assert seen["argv"] == ["grok", "login"]
    assert seen_lines == ["Open https://auth.x.ai/oauth2/authorize\n"]
    # stdout/stderr plumbing is unchanged — only the env and console flags differ.
    assert seen["stdout"] is subprocess.PIPE
    assert seen["stderr"] is subprocess.STDOUT
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    child_env = seen["env"]
    assert "CLAUDE_CODE_ENTRYPOINT" not in child_env
    assert "ANTHROPIC_API_KEY" not in child_env
    assert child_env["GROK_HOME"] == "C:\\Users\\tester\\.grok"
    assert child_env["PATH"] == "C:\\bin"
    # The actual bug: a child on our console could SetConsoleTitle the tab.
    assert seen["creationflags"] == subprocess.CREATE_NO_WINDOW


def _c_test_run_cli_streaming_sanitizes_an_explicit_env_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied env is sanitized too, not forwarded verbatim."""
    seen = _record_popen(monkeypatch)
    base = {"PATH": "C:\\bin", "CLAUDE_CONFIG_DIR": "C:\\cfg", "XAI_API_KEY": "xai-key"}

    run_cli_streaming("agy", env=base, timeout=5.0)

    child_env = seen["env"]
    assert "CLAUDE_CONFIG_DIR" not in child_env
    assert child_env["PATH"] == "C:\\bin" and child_env["XAI_API_KEY"] == "xai-key"
    # The caller's dict is not mutated in place.
    assert "CLAUDE_CONFIG_DIR" in base


def _c_test_run_cli_passes_console_isolation_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_platform(monkeypatch, "win32")
    seen = _record_run(monkeypatch)
    run_cli("claude", "auth", "status")
    assert seen["creationflags"] == subprocess.CREATE_NO_WINDOW


def _c_test_run_checked_delegates_through_run_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_checked reaches the child via run_cli, so it inherits both guards."""
    _force_platform(monkeypatch, "win32")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-lite-llm-routing-key")
    seen = _record_run(monkeypatch, stdout="ok")

    proc = run_checked("claude", "auth", "status", timeout=12.5)

    assert proc.returncode == 0 and proc.stdout == "ok"
    assert seen["argv"] == ["claude", "auth", "status"]
    assert seen["timeout"] == 12.5
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert seen["creationflags"] == subprocess.CREATE_NO_WINDOW

    _record_run(monkeypatch, returncode=3, stdout="nope")
    with pytest.raises(RuntimeError, match="exited with status 3"):
        run_checked("claude", "auth", "status")


def _c_test_console_isolation_kwargs_is_platform_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_platform(monkeypatch, "linux")
    assert console_isolation_kwargs() == {}
    _force_platform(monkeypatch, "darwin")
    assert console_isolation_kwargs() == {}
    _force_platform(monkeypatch, "win32")
    assert console_isolation_kwargs() == {"creationflags": subprocess.CREATE_NO_WINDOW}


def _c_test_console_isolation_kwargs_never_raises_on_missing_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """subprocess.CREATE_NO_WINDOW only exists on win32 builds — never assume it."""
    monkeypatch.setattr(cli_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.delattr(cli_mod.subprocess, "CREATE_NO_WINDOW", raising=False)
    _force_platform(monkeypatch, "win32")
    assert console_isolation_kwargs() == {}
    _force_platform(monkeypatch, "linux")
    assert console_isolation_kwargs() == {}


def _c_test_kite_tui_vars_are_stripped_but_kite_config_is_kept() -> None:
    """Kite's own terminal knobs are the *parent's*; KITE_HOME/OFFLINE are config."""
    base = {
        "KITE_LOADER": "dots",
        "KITE_MOUSE": "1",
        "KITE_BUSY_ENTER": "queue",
        "KITE_COMPACT_UI": "1",
        "KITE_TYPED_PICK": "1",
        "KITE_NO_MOUSE_PICK": "1",
        "KITE_PICK_DEBUG": "1",
        "KITE_THEME": "nord",
        "KITE_FONT": "nerd",
        "KITE_HOME": "/home/tester/.kite",
        "KITE_OFFLINE": "1",
        "PATH": "/usr/bin",
    }
    child_env = provider_cli_env(base)
    for var in (
        "KITE_LOADER",
        "KITE_MOUSE",
        "KITE_BUSY_ENTER",
        "KITE_COMPACT_UI",
        "KITE_TYPED_PICK",
        "KITE_NO_MOUSE_PICK",
        "KITE_PICK_DEBUG",
        "KITE_THEME",
        "KITE_FONT",
    ):
        assert var not in child_env, var
    assert child_env["KITE_HOME"] == "/home/tester/.kite"
    assert child_env["KITE_OFFLINE"] == "1"
    assert child_env["PATH"] == "/usr/bin"
    # Every KITE_* name that survives is config, never a TUI knob.
    assert not {name for name in child_env if name.startswith("KITE_")} - {
        "KITE_HOME",
        "KITE_OFFLINE",
    }
    # os.environ is the default source and is never mutated.
    assert provider_cli_env() is not provider_cli_env()


def _c_test_platform_module_is_the_real_sys() -> None:
    """The platform checks must follow the live interpreter, not a copied constant."""
    assert cli_mod.sys is sys
    assert cli_mod.subprocess is subprocess


# No test may reach a real provider binary: the recorders must be what every
# helper actually calls, for argv that does not exist on PATH.
def _c_test_helpers_are_intercepted_never_a_real_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    run_seen = _record_run(monkeypatch)
    popen_seen = _record_popen(monkeypatch)
    missing = "kite-no-such-provider-binary"

    assert run_cli(missing, "auth", "status").returncode == 0
    assert popen_seen == {}
    assert run_seen["argv"] == [missing, "auth", "status"]

    assert run_cli_streaming(missing, "login").returncode == 0
    assert popen_seen["argv"] == [missing, "login"]
    assert run_seen["argv"] == [missing, "auth", "status"]  # unchanged


def test_batch_00(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consolidated (bodies unchanged): env strip + preserve + streaming sanitize + explicit env."""
    _c_test_run_cli_strips_session_identity_env(monkeypatch)
    _c_test_run_cli_preserves_what_a_child_login_needs(monkeypatch)
    _c_test_run_cli_streaming_sanitizes_env_and_isolates_console(monkeypatch)
    _c_test_run_cli_streaming_sanitizes_an_explicit_env_argument(monkeypatch)


def test_batch_01(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consolidated (bodies unchanged): console-isolation pass-through + run_checked + platform scoping."""
    _c_test_run_cli_passes_console_isolation_kwargs(monkeypatch)
    _c_test_run_checked_delegates_through_run_cli(monkeypatch)
    _c_test_console_isolation_kwargs_is_platform_scoped(monkeypatch)
    _c_test_console_isolation_kwargs_never_raises_on_missing_constant(monkeypatch)


def test_batch_02(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consolidated (bodies unchanged): TUI vars + platform identity + interception."""
    _c_test_kite_tui_vars_are_stripped_but_kite_config_is_kept()
    _c_test_platform_module_is_the_real_sys()
    _c_test_helpers_are_intercepted_never_a_real_binary(monkeypatch)
