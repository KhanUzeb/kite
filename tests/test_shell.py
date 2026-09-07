"""Shell invocation helpers."""

from __future__ import annotations

import sys

from kite.env.shell import resolve_shell_invocation, sanitize_shell_line


def test_sanitize_shell_line_strips_control_chars() -> None:
    assert sanitize_shell_line("hello\r\nworld\t!") == "hello world !"
    assert sanitize_shell_line("ok\x00bad") == "okbad"


def test_resolve_shell_unix_passthrough() -> None:
    argv, cmd = resolve_shell_invocation("pytest -q")
    if sys.platform == "win32":
        assert argv is None
    else:
        assert argv is None
        assert cmd == "pytest -q"


def test_resolve_shell_powershell_on_windows(monkeypatch) -> None:
    monkeypatch.setattr("kite.env.shell.sys.platform", "win32")
    argv, _ = resolve_shell_invocation("Get-ChildItem .")
    assert argv is not None
    assert argv[0] == "powershell"
    assert "Get-ChildItem ." in argv


def test_resolve_shell_bash_for_unix_markers_on_windows(monkeypatch) -> None:
    monkeypatch.setattr("kite.env.shell.sys.platform", "win32")
    monkeypatch.setattr("kite.env.shell.shutil.which", lambda name: "/bin/bash" if name == "bash" else None)
    argv, _ = resolve_shell_invocation("grep -r foo .")
    assert argv == ["/bin/bash", "-lc", "grep -r foo ."]
