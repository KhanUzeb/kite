"""GitHub gh tools: auth-failure hints + gh_auth status (no live gh)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kite.tools.github import _auth_hint, make_github_tools


def test_auth_failure_hint_markers() -> None:
    assert _auth_hint("error: not logged in to github.com") is not None
    hint = _auth_hint("Bad credentials (HTTP 401)")
    assert hint is not None and "kite gh auth login" in hint
    assert _auth_hint("To access this, run gh auth login") is not None
    assert _auth_hint("all good") is None


@pytest.mark.parametrize(
    ("tool_name", "args", "expected"),
    [
        (
            "gh_issue",
            {"number": 7, "repo": "acme/x"},
            ["issue", "view", "7", "--json", "title,body,state,labels,url,comments", "--repo", "acme/x"],
        ),
        (
            "gh_pr",
            {"number": 8},
            ["pr", "view", "8", "--json", "title,body,state,url,commits,files,reviews"],
        ),
        (
            "gh_prs",
            {"limit": 3, "repo": "acme/x"},
            ["pr", "list", "--limit", "3", "--json", "number,title,state,url,headRefName", "--repo", "acme/x"],
        ),
        (
            "gh_runs",
            {},
            ["run", "list", "--limit", "5", "--json", "databaseId,status,conclusion,name,url,headBranch"],
        ),
        (
            "gh_run",
            {"run_id": 42, "repo": "acme/x"},
            ["run", "view", "42", "--json", "status,conclusion,jobs,url", "--repo", "acme/x"],
        ),
    ],
)
def test_gh_read_tools_build_expected_commands(tool_name, args, expected) -> None:
    """`--repo`/`--json`/`--limit` shape must be identical for every read tool."""
    tools = {tool.name: tool for tool in make_github_tools()}
    with patch("kite.tools.github._gh_available", return_value=True):
        with patch("kite.tools.github.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            out = tools[tool_name].run(args)

    assert out["ok"] is True
    assert run.call_args.args[0] == ["gh", *expected]


def test_run_gh_appends_auth_hint_and_gh_auth_tool() -> None:
    tools = {t.name: t for t in make_github_tools()}
    with patch("kite.tools.github._gh_available", return_value=True):
        with patch("kite.tools.github.subprocess.run") as run:
            def auth_failure(_cmd, **kwargs):
                kwargs["stdout"].write("To access this, run gh auth login")
                return MagicMock(returncode=1)

            run.side_effect = auth_failure
            out = tools["gh_issue"].run({"number": 1})
    assert out["ok"] is False
    assert "kite gh auth login" in out["output"]

    with patch("kite.tools.github._gh_available", return_value=True):
        with patch("kite.tools.github.subprocess.run") as run:
            def auth_success(_cmd, **kwargs):
                kwargs["stdout"].write("Logged in to github.com account octo")
                return MagicMock(returncode=0)

            run.side_effect = auth_success
            ok = tools["gh_auth"].run({})
    assert ok["ok"] is True
    assert "GitHub auth ok" in ok["output"]

    with patch("kite.tools.github._gh_available", return_value=False):
        missing = tools["gh_auth"].run({})
    assert missing["ok"] is False
    assert "gh CLI not found" in missing["output"]

    with patch("kite.tools.github._gh_available", return_value=True):
        with patch("kite.tools.github.subprocess.run") as run:
            def huge_result(_cmd, **kwargs):
                kwargs["stdout"].write("api_key=" + "s" * 500_000 + "\nshort result\n")
                return MagicMock(returncode=0)

            run.side_effect = huge_result
            bounded = tools["gh_issue"].run({"number": 1})
    assert "oversized output line omitted" in bounded["output"]
    assert "short result" in bounded["output"] and "api_key" not in bounded["output"]
    assert len(bounded["output"]) < 1000
