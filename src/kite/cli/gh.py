"""`kite gh` — GitHub PRs and issues from your terminal.

Thin wrapper over the `gh` CLI so you never leave kite to triage:
auth comes impromptu from your shell — `gh auth login` credentials or an
exported GH_TOKEN/GITHUB_TOKEN (re-injected past the child-env secret filter,
which otherwise strips them). `--repo owner/name` targets any repo from any
directory; inside a checkout the current repo is used.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess

_ISSUE_JSON = "title,body,state,labels,url,comments"
_PR_JSON = "title,body,state,url,commits,files,reviews"
_PR_LIST_JSON = "number,title,state,url,headRefName"
_ISSUE_LIST_JSON = "number,title,state,url,labels"

def _console():
    from kite.ui.style import make_console

    return make_console(stderr=True)


def _gh_env() -> dict[str, str]:
    # Impromptu tokens: ambient GH_TOKEN/GITHUB_TOKEN survive the child-env
    # secret filter for gh children (see guardrails/env_filter.with_gh_tokens).
    from kite.guardrails.env_filter import filtered_child_env, with_gh_tokens

    return with_gh_tokens(filtered_child_env())


def _run_gh(cmd: list[str], *, cwd: str, interactive: bool = False, stdin_text: str | None = None) -> tuple[int, str]:
    """Run gh, returning (returncode, combined output). Tokens flow impromptu.

    Interactive mode inherits stdio so `gh auth login` prompts render.
    """
    if shutil.which("gh") is None:
        return 127, "gh CLI not found — install https://cli.github.com then `gh auth login` (or export GH_TOKEN)"
    try:
        if interactive:
            proc = subprocess.run(
                ["gh", *cmd],
                cwd=cwd,
                env=_gh_env(),
                timeout=600,
            )
            return proc.returncode, ""
        proc = subprocess.run(
            ["gh", *cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            cwd=cwd,
            env=_gh_env(),
            input=stdin_text,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr and proc.returncode != 0 else "")
    return proc.returncode, out.strip() or "(empty)"


def _with_repo(cmd: list[str], repo: str | None) -> list[str]:
    if repo:
        cmd = [*cmd, "--repo", repo]
    return cmd


def _auth_cmd(args, *, cwd: str, console) -> int:  # noqa: ANN001, ANN201
    """OAuth / PAT login, status, logout. Interactive login inherits stdio."""
    import sys

    action = getattr(args, "gh_action", None) or "status"
    if action == "status":
        rc, out = _run_gh(["auth", "status"], cwd=cwd)
        print(out)
        if rc != 0:
            console.print("[kite.muted]tip: `kite gh auth login` (browser/device), or export GH_TOKEN per-shell.[/]")
        return rc
    if action == "logout":
        rc, out = _run_gh(["auth", "logout"], cwd=cwd)
        if out:
            print(out)
        return rc
    if action == "login":
        if bool(getattr(args, "with_token", False)):
            if sys.stdin.isatty():
                console.print("[red]--with-token reads the PAT from stdin[/]  —  e.g. $env:GH_TOKEN | kite gh auth login --with-token")
                return 2
            token = sys.stdin.read().strip().split()
            if not token:
                console.print("[red]empty token on stdin[/]")
                return 2
            rc, out = _run_gh(["auth", "login", "--with-token"], cwd=cwd, stdin_text=token[0])
            if out:
                print(out)
            if rc == 0:
                console.print("[kite.success]GitHub auth stored[/]  [kite.muted](gh credential store)[/]")
            return rc
        if not sys.stdin.isatty():
            console.print("[red]no TTY for the browser/device flow[/]  —  pipe a PAT: $env:GH_TOKEN | kite gh auth login --with-token")
            return 2
        console.print("[kite.muted]completing `gh auth login` — follow its prompts (browser or device code).[/]")
        rc, _ = _run_gh(["auth", "login"], cwd=cwd, interactive=True)
        if rc == 0:
            console.print("[kite.success]GitHub auth stored[/]")
        return rc
    console.print("[red]usage:[/]  kite gh auth [login|status|logout]")
    return 2


def cmd_gh(args: argparse.Namespace) -> int:
    console = _console()
    kind = getattr(args, "gh_kind", None)
    action = getattr(args, "gh_action", None)
    repo = (getattr(args, "repo", None) or "").strip() or None
    cwd = getattr(args, "cwd", None) or os.getcwd()
    as_json = bool(getattr(args, "json", False))
    limit = getattr(args, "limit", 10) or 10

    if kind == "auth":
        return _auth_cmd(args, cwd=cwd, console=console)

    if kind == "issue" and action == "view":
        number = str(getattr(args, "number", "") or "").strip()
        if not number:
            console.print("[red]issue number required[/]  —  kite gh issue view <n>")
            return 2
        fields = _ISSUE_JSON if as_json else "title,body,state,labels,url"
        rc, out = _run_gh(_with_repo(["issue", "view", number, "--json", fields], repo), cwd=cwd)
        print(out)
        return rc

    if kind == "issue" and action == "list":
        fields = _ISSUE_LIST_JSON
        cmd = ["issue", "list", "--limit", str(limit), "--json", fields]
        rc, out = _run_gh(_with_repo(cmd, repo), cwd=cwd)
        print(out)
        return rc

    if kind == "issue" and action == "create":
        title = str(getattr(args, "title", "") or "").strip()
        body = str(getattr(args, "body", "") or "")
        if not title:
            console.print("[red]--title required[/]  —  kite gh issue create --title \"…\" [--body \"…\"]")
            return 2
        rc, out = _run_gh(_with_repo(["issue", "create", "--title", title, "--body", body], repo), cwd=cwd)
        print(out)
        return rc

    if kind == "issue" and action == "comment":
        number = str(getattr(args, "number", "") or "").strip()
        body = str(getattr(args, "body", "") or "")
        if not number or not body:
            console.print("[red]usage:[/]  kite gh issue comment <n> --body \"…\"")
            return 2
        rc, out = _run_gh(_with_repo(["issue", "comment", number, "--body", body], repo), cwd=cwd)
        print(out)
        return rc

    if kind == "pr" and action == "view":
        number = str(getattr(args, "number", "") or "").strip()
        if not number:
            console.print("[red]PR number required[/]  —  kite gh pr view <n>")
            return 2
        rc, out = _run_gh(_with_repo(["pr", "view", number, "--json", _PR_JSON], repo), cwd=cwd)
        print(out)
        return rc

    if kind == "pr" and action == "list":
        cmd = ["pr", "list", "--limit", str(limit), "--json", _PR_LIST_JSON]
        rc, out = _run_gh(_with_repo(cmd, repo), cwd=cwd)
        print(out)
        return rc

    if kind == "pr" and action == "create":
        title = str(getattr(args, "title", "") or "").strip()
        body = str(getattr(args, "body", "") or "")
        if not title:
            console.print("[red]--title required[/]  —  kite gh pr create --title \"…\" [--body \"…\"]")
            return 2
        cmd = ["pr", "create", "--title", title, "--body", body]
        if getattr(args, "draft", False):
            cmd.append("--draft")
        rc, out = _run_gh(_with_repo(cmd, repo), cwd=cwd)
        print(out)
        return rc

    console.print("[red]usage:[/]  kite gh (issue view|list|create|comment | pr view|list|create | auth)")
    return 2


def add_gh_parser(sub) -> None:  # noqa: ANN001
    import argparse

    def _add_scope(p) -> None:  # noqa: ANN001
        # Accept scope flags after the action too (`gh issue view 12 --repo o/r`).
        # SUPPRESS keeps the parent-level value when the leaf flag is absent.
        p.add_argument("--repo", default=argparse.SUPPRESS, help="owner/repo (default: checkout in --cwd)")
        p.add_argument("--cwd", default=argparse.SUPPRESS, help="Working directory")
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Raw JSON output (view/list)")

    gh = sub.add_parser("gh", help="GitHub issues + PRs via gh CLI (GH_TOKEN works, no setup)")
    gh.add_argument("--repo", default="", help="owner/repo (default: checkout in --cwd)")
    gh.add_argument("--cwd", default=os.getcwd(), help="Working directory")
    gh.add_argument("--json", action="store_true", help="Raw JSON output (view/list)")
    kind = gh.add_subparsers(dest="gh_kind", metavar="KIND")

    auth_p = kind.add_parser("auth", help="GitHub auth: login (browser/device/PAT) | status | logout")
    auth_p.add_argument("gh_action", nargs="?", choices=["login", "status", "logout"], default="status")
    auth_p.add_argument("--with-token", action="store_true", help="Read a PAT from stdin (headless login)")
    auth_p.set_defaults(func=cmd_gh)

    issue = kind.add_parser("issue", help="Issues: view | list | create | comment")
    issue.set_defaults(func=cmd_gh)
    iaction = issue.add_subparsers(dest="gh_action", metavar="ACTION")
    iview = iaction.add_parser("view", help="Show one issue")
    iview.add_argument("number", help="Issue number")
    _add_scope(iview)
    iview.set_defaults(func=cmd_gh)
    ilist = iaction.add_parser("list", help="List issues")
    ilist.add_argument("--limit", type=int, default=10)
    _add_scope(ilist)
    ilist.set_defaults(func=cmd_gh)
    icreate = iaction.add_parser("create", help="Open an issue")
    icreate.add_argument("--title", required=False, default="")
    icreate.add_argument("--body", default="")
    _add_scope(icreate)
    icreate.set_defaults(func=cmd_gh)
    icomment = iaction.add_parser("comment", help="Comment on an issue")
    icomment.add_argument("number", help="Issue number")
    icomment.add_argument("--body", required=False, default="")
    _add_scope(icomment)
    icomment.set_defaults(func=cmd_gh)

    pr = kind.add_parser("pr", help="PRs: view | list | create")
    pr.set_defaults(func=cmd_gh)
    paction = pr.add_subparsers(dest="gh_action", metavar="ACTION")
    pview = paction.add_parser("view", help="Show one PR")
    pview.add_argument("number", help="PR number")
    _add_scope(pview)
    pview.set_defaults(func=cmd_gh)
    plist = paction.add_parser("list", help="List PRs")
    plist.add_argument("--limit", type=int, default=10)
    _add_scope(plist)
    plist.set_defaults(func=cmd_gh)
    pcreate = paction.add_parser("create", help="Open a PR from the current branch")
    pcreate.add_argument("--title", required=False, default="")
    pcreate.add_argument("--body", default="")
    pcreate.add_argument("--draft", action="store_true")
    _add_scope(pcreate)
    pcreate.set_defaults(func=cmd_gh)
