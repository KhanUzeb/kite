"""GitHub integration via gh CLI — issues, PRs, CI (no extra API keys if gh auth'd)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from kite.tools import Tool

# Tokens gh accepts itself — re-injected past the child-env secret filter so
# an exported GH_TOKEN/GITHUB_TOKEN works impromptu (no kite-side setup).


_AUTH_FAILURE_MARKERS = (
    "not logged in",
    "authentication required",
    "bad credentials",
    "http 401",
    "http 403",
    "resource not accessible",
    "gh auth login",
)

_AUTH_HINT = (
    "hint: GitHub auth missing — run `kite gh auth login` (browser/device/PAT) "
    "or export GH_TOKEN for this shell, then retry"
)


def _auth_hint(output: str) -> str | None:
    lowered = (output or "").lower()
    if any(marker in lowered for marker in _AUTH_FAILURE_MARKERS):
        return _AUTH_HINT
    return None


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _gh_env() -> dict[str, str]:
    from kite.guardrails.env_filter import filtered_child_env, with_gh_tokens

    return with_gh_tokens(filtered_child_env())


def _run_gh(args: list[str], *, timeout: int = 30) -> dict[str, Any]:
    if not _gh_available():
        return {
            "ok": False,
            "error": "gh CLI not found — install https://cli.github.com and run gh auth login",
            "output": "gh CLI not found",
        }
    cmd = ["gh", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_gh_env(),
        )
        output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        text = output.strip() or "(empty)"
        if proc.returncode != 0:
            hint = _auth_hint(text)
            if hint:
                text = f"{text}\n{hint}"
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": text,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "output": "", "error": f"timeout after {timeout}s"}
    except OSError as e:
        return {"ok": False, "error": str(e), "output": str(e)}


def make_github_tools(*, enabled: bool = True) -> list[Tool]:
    if not enabled:
        return []

    def issue_view(args: dict[str, Any]) -> dict[str, Any]:
        num = str(args.get("number") or args.get("issue") or "")
        if not num:
            return {"ok": False, "error": "number required", "output": "number required"}
        repo = args.get("repo")
        cmd = ["issue", "view", num, "--json", "title,body,state,labels,url,comments"]
        if repo:
            cmd.extend(["--repo", str(repo)])
        return _run_gh(cmd)

    def pr_view(args: dict[str, Any]) -> dict[str, Any]:
        num = str(args.get("number") or args.get("pr") or "")
        if not num:
            return {"ok": False, "error": "number required", "output": "number required"}
        repo = args.get("repo")
        cmd = ["pr", "view", num, "--json", "title,body,state,url,commits,files,reviews"]
        if repo:
            cmd.extend(["--repo", str(repo)])
        return _run_gh(cmd)

    def pr_list(args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 10)
        repo = args.get("repo")
        cmd = ["pr", "list", "--limit", str(limit), "--json", "number,title,state,url,headRefName"]
        if repo:
            cmd.extend(["--repo", str(repo)])
        return _run_gh(cmd)

    def run_list(args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 5)
        repo = args.get("repo")
        cmd = ["run", "list", "--limit", str(limit), "--json", "databaseId,status,conclusion,name,url,headBranch"]
        if repo:
            cmd.extend(["--repo", str(repo)])
        return _run_gh(cmd)

    def run_view(args: dict[str, Any]) -> dict[str, Any]:
        run_id = str(args.get("run_id") or args.get("id") or "")
        if not run_id:
            return {"ok": False, "error": "run_id required", "output": "run_id required"}
        repo = args.get("repo")
        cmd = ["run", "view", run_id, "--json", "status,conclusion,jobs,url"]
        if repo:
            cmd.extend(["--repo", str(repo)])
        return _run_gh(cmd)

    def auth_status(args: dict[str, Any]) -> dict[str, Any]:
        """Read-only auth probe — call before gh_* tools when auth is uncertain."""
        result = _run_gh(["auth", "status"])
        if result.get("ok"):
            users = str(result.get("output") or "").strip()
            return {"ok": True, "output": f"GitHub auth ok\n{users}".strip()}
        return result

    return [
        Tool(
            name="gh_auth",
            description="Check GitHub auth status via gh CLI (read-only). Call when gh_* tools report auth errors.",
            parameters={
                "type": "object",
                "properties": {},
            },
            execute_fn=auth_status,
        ),
        Tool(
            name="gh_issue",
            description="View a GitHub issue via gh CLI (requires gh auth). Returns JSON fields.",
            parameters={
                "type": "object",
                "properties": {
                    "number": {"type": "integer", "description": "Issue number"},
                    "repo": {"type": "string", "description": "owner/repo (default: current repo)"},
                },
                "required": ["number"],
            },
            execute_fn=issue_view,
        ),
        Tool(
            name="gh_pr",
            description="View a GitHub pull request via gh CLI.",
            parameters={
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "repo": {"type": "string"},
                },
                "required": ["number"],
            },
            execute_fn=pr_view,
        ),
        Tool(
            name="gh_prs",
            description="List open pull requests for the repo.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "repo": {"type": "string"},
                },
            },
            execute_fn=pr_list,
        ),
        Tool(
            name="gh_runs",
            description="List recent GitHub Actions workflow runs.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "repo": {"type": "string"},
                },
            },
            execute_fn=run_list,
        ),
        Tool(
            name="gh_run",
            description="View a specific GitHub Actions run (status, jobs, conclusion).",
            parameters={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "repo": {"type": "string"},
                },
                "required": ["run_id"],
            },
            execute_fn=run_view,
        ),
    ]
