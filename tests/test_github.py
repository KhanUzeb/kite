"""GitHub gh tools: auth-failure hints + gh_auth status (no live gh)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kite.tools.github import _auth_hint, make_github_tools


def test_auth_failure_hint_markers() -> None:
    assert _auth_hint("error: not logged in to github.com") is not None
    hint = _auth_hint("Bad credentials (HTTP 401)")
    assert hint is not None and "kite gh auth login" in hint
    assert _auth_hint("To access this, run gh auth login") is not None
    assert _auth_hint("all good") is None


def test_run_gh_appends_auth_hint_and_gh_auth_tool() -> None:
    tools = {t.name: t for t in make_github_tools()}
    assert "gh_auth" in tools
    assert tools["gh_auth"].parameters == {"type": "object", "properties": {}}

    with patch("kite.tools.github._gh_available", return_value=True):
        with patch("kite.tools.github.subprocess.run") as run:
            run.return_value = MagicMock(
                stdout="", stderr="To access this, run gh auth login", returncode=1
            )
            out = tools["gh_issue"].run({"number": 1})
    assert out["ok"] is False
    assert "kite gh auth login" in out["output"]

    with patch("kite.tools.github._gh_available", return_value=True):
        with patch("kite.tools.github.subprocess.run") as run:
            run.return_value = MagicMock(
                stdout="Logged in to github.com account octo", stderr="", returncode=0
            )
            ok = tools["gh_auth"].run({})
    assert ok["ok"] is True
    assert "GitHub auth ok" in ok["output"]

    with patch("kite.tools.github._gh_available", return_value=False):
        missing = tools["gh_auth"].run({})
    assert missing["ok"] is False
    assert "gh CLI not found" in missing["output"]
