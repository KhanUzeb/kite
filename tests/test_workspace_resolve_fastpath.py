"""Behavior tests for the already-resolved workspace-base fast path."""

from __future__ import annotations

import os
import subprocess

import pytest

from kite.application.tools import _targets_outside_workspace
from kite.guardrails.sandbox import resolve_in_workspace, workspace_root


def test_fast_path_matches_default_resolution(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "src").mkdir()
    root_resolved = workspace_root(root)

    for raw in ("src/app.py", "./src/../src/app.py", str(root / "src" / "app.py")):
        assert resolve_in_workspace(raw, root) == resolve_in_workspace(
            raw, root_resolved, cwd_is_root=True
        )


def test_fast_path_keeps_symlink_escape_detection(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "vault"
    workspace.mkdir()
    outside.mkdir()
    link = workspace / "escape"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True, capture_output=True, text=True, timeout=30,
        )
    else:
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlinks not permitted on this OS: {exc}")
    try:
        _assert_symlink_escape(workspace, outside)
    finally:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", str(link)], check=True, capture_output=True, timeout=30)
        else:
            link.unlink()


def _assert_symlink_escape(workspace, outside) -> None:
    resolved = resolve_in_workspace("escape/secret.txt", workspace)
    assert not resolved.is_relative_to(workspace.resolve())
    assert resolved.is_relative_to(outside.resolve())

    assert _targets_outside_workspace("read", {"path": "escape/secret.txt"}, str(workspace)) is True
    assert _targets_outside_workspace("read", {"path": "src/app.py"}, str(workspace)) is False


def test_fast_path_does_not_weaken_protected_path_checks(tmp_path, monkeypatch) -> None:
    from kite.guardrails import sandbox

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    secret = home / ".ssh" / "secret"
    secret.parent.mkdir()

    root = workspace_root(tmp_path / "workspace")
    resolved = resolve_in_workspace(str(secret), root, cwd_is_root=True)

    assert sandbox.is_protected(resolved)
    assert resolved == resolve_in_workspace(str(secret), root)
