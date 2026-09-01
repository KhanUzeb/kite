"""Permission gate with memory: once / session / always-this-pattern."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Literal

from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text

from kite.config import kite_home
from kite.agent.mode import MUTATING_TOOLS, AgentMode, ApprovalMode
from kite.ui.diff import count_diff_lines, diff_path, render_diff_stat
from kite.ui.style import GUTTER, SYMBOL_WARN

Decision = Literal["allow", "session", "always", "deny", "stop"]

GitBashKind = Literal["read", "write", "other"]

# Flags that consume the next token (git -C /path status).
_GIT_VALUE_FLAGS = frozenset({"-c", "--git-dir", "--work-tree", "--namespace"})

# Subcommands that mutate the repo or working tree.
_GIT_WRITE_SUBS = frozenset({
    "add", "am", "checkout", "cherry-pick", "clean", "clone", "commit", "fetch", "gc",
    "init", "merge", "pull", "push", "rebase", "reset", "restore", "revert", "rm",
    "switch", "submodule", "filter-branch", "update-ref", "update-index",
})

# Subcommands that only inspect state.
_GIT_READ_SUBS = frozenset({
    "status", "log", "show", "diff", "blame", "grep", "describe", "shortlog",
    "ls-files", "ls-tree", "whatchanged", "rev-parse", "cat-file", "count-objects",
    "help", "version", "reflog", "config",
})


def _git_command_tokens(command: str) -> list[str]:
    """Return git subcommand tokens after the ``git`` binary (lowercased)."""
    text = command or ""
    match = re.search(r"(?i)(?:^|[;&|]\s*)git\b", text)
    if not match:
        return []
    rest = text[match.end() :].strip()
    if not rest:
        return []
    parts = rest.split()
    tokens: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        low = part.lower()
        if low in _GIT_VALUE_FLAGS:
            i += 2 if i + 1 < len(parts) else 1
            continue
        if low.startswith("-") and low not in {"-d", "-D", "-m", "-M", "-b"}:
            i += 1
            continue
        tokens.append(low)
        i += 1
    return tokens


def git_bash_kind(command: str) -> GitBashKind:
    """Classify a bash git invocation as read-only, mutating, or non-git/unknown."""
    tokens = _git_command_tokens(command)
    if not tokens:
        if re.search(r"(?i)(?:^|[;&|]\s*)git\b", command or ""):
            return "other"
        return "other"

    sub, *rest = tokens
    if sub in _GIT_WRITE_SUBS:
        return "write"
    if sub == "stash":
        return "write" if rest and rest[0] in {"pop", "apply", "drop", "clear", "push", "store"} else "read"
    if sub == "branch":
        if any(x in rest for x in ("-d", "-D", "-m", "-M", "--delete", "--move")):
            return "write"
        return "read"
    if sub == "remote":
        return "write" if rest and rest[0] in {"add", "remove", "rm", "set-url", "rename", "prune"} else "read"
    if sub == "tag":
        if rest and rest[0] in {"-l", "--list", "list"}:
            return "read"
        if rest and not rest[0].startswith("-"):
            return "write"
        return "read"
    if sub == "config":
        if not rest:
            return "read"
        if rest[0] in {"--get", "--list", "-l"} or any(r.startswith("--get") for r in rest):
            return "read"
        if len(rest) >= 2 or "=" in " ".join(rest):
            return "write"
        return "read"
    if sub in _GIT_READ_SUBS:
        return "read"
    return "other"


def is_git_write(command: str) -> bool:
    return git_bash_kind(command) == "write"


def is_git_read(command: str) -> bool:
    return git_bash_kind(command) == "read"


def action_pattern(tool: str, arguments: dict[str, Any]) -> str:
    """Stable pattern used for always-allow matching."""
    if tool == "bash":
        cmd = str(arguments.get("command") or "").strip()
        parts = cmd.split()
        if not parts:
            return "bash:*"
        head = parts[0]
        if head.lower() in {"git", "gh"} and len(parts) >= 2:
            return f"bash:{head} {parts[1]}*"
        return f"bash:{head}*"
    path = arguments.get("path") or arguments.get("root") or ""
    if path:
        return f"{tool}:{path}"
    return f"{tool}:*"


def needs_approval(
    tool: str,
    mode: AgentMode,
    approval: ApprovalMode,
    *,
    command: str = "",
    trusted_paths: list[str] | None = None,
    workspace_cwd: str | None = None,
    bash_cwd: str | None = None,
) -> bool:
    if tool not in MUTATING_TOOLS:
        return False
    if mode is AgentMode.PLAN and tool != "todo_write":
        return True  # will be auto-denied by the agent; still surfaces
    if approval is ApprovalMode.READONLY:
        return True
    if tool == "bash":
        kind = git_bash_kind(command)
        if kind == "read":
            return False
        if kind == "write":
            return True
    if approval is ApprovalMode.AUTO:
        return False
    if approval is ApprovalMode.TRUST:
        if tool != "bash":
            return False
        if trusted_paths and workspace_cwd:
            from kite.guardrails.sandbox import clamp_cwd, cwd_in_trusted, workspace_root

            root = workspace_root(workspace_cwd)
            workdir, _ = clamp_cwd(bash_cwd, root)
            if workdir and cwd_in_trusted(workdir, root, trusted_paths):
                return False
        cmd = command.lower()
        destructive = any(
            tok in cmd
            for tok in (
                "rm -",
                "git push",
                "git commit",
                "git reset",
                "git merge",
                "git rebase",
                "git pull",
                "chmod",
                "curl",
                "wget",
                "pip install",
                "npm install",
            )
        )
        return destructive
    return True


@dataclass
class ApprovalPolicy:
    """In-memory + on-disk pattern memory."""

    session_patterns: set[str] = field(default_factory=set)
    always_patterns: set[str] = field(default_factory=set)

    @classmethod
    def load(cls) -> ApprovalPolicy:
        path = kite_home() / "approvals.json"
        always: set[str] = set()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                always = set(data.get("always") or [])
            except (OSError, json.JSONDecodeError):
                always = set()
        return cls(always_patterns=always)

    def save(self) -> None:
        path = kite_home() / "approvals.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"always": sorted(self.always_patterns)}, indent=2),
            encoding="utf-8",
        )

    def remembered(self, pattern: str) -> bool:
        for stored in (*self.always_patterns, *self.session_patterns):
            if pattern != stored and not fnmatch(pattern, stored):
                continue
            # Approving `git status` used to match `bash:git*` and then allow push.
            if re.search(r"(?i)bash:git\s+(commit|push|reset|rebase)", pattern):
                if not re.search(r"(?i)git\s+(commit|push|reset|rebase)", stored):
                    continue
            return True
        return False

    def remember(self, pattern: str, *, always: bool) -> None:
        if always:
            self.always_patterns.add(pattern)
            self.save()
        else:
            self.session_patterns.add(pattern)


def render_approval_panel(tool: str, arguments: dict[str, Any], *, diff: str = "", reason: str = "") -> Text:
    """Compact gate — Codex keeps this in the composer, not a boxed panel."""
    body = Text()
    body.append(f"{SYMBOL_WARN}  approve ", style="kite.pending")
    body.append(tool, style="bold")
    body.append("\n")
    if reason:
        body.append(f"{GUTTER}{reason}\n", style="kite.muted")

    if tool == "bash":
        cmd = str(arguments.get("command") or "")
        cwd = arguments.get("cwd")
        body.append(f"{GUTTER}$ {cmd}\n", style="bold")
        if cwd:
            body.append(f"{GUTTER}cwd {cwd}\n", style="kite.muted")
    else:
        for key in ("path", "root", "pattern", "query"):
            if arguments.get(key):
                body.append(f"{GUTTER}{key}={arguments[key]}\n")
        if diff:
            added, deleted = count_diff_lines(diff)
            if added or deleted:
                body.append(GUTTER)
                body.append_text(render_diff_stat(added, deleted, path=diff_path(diff)))
                body.append("\n")
            preview = "\n".join(diff.splitlines()[:80])
            body.append("\n")
            for line in preview.splitlines():
                style = "kite.diff.meta"
                if line.startswith("+") and not line.startswith("+++"):
                    style = "kite.diff.add"
                elif line.startswith("-") and not line.startswith("---"):
                    style = "kite.diff.del"
                elif line.startswith("@@"):
                    style = "kite.diff.hunk"
                body.append(f"{GUTTER}{line}\n", style=style)
            extra = max(0, len(diff.splitlines()) - 80)
            if extra:
                body.append(f"{GUTTER}… {extra} more diff lines\n", style="kite.muted")

    body.append("\n")
    body.append(f"{GUTTER}[a] once  [s] session  [p] always  [n] deny  [q] stop\n", style="kite.muted")
    return body


def prompt_approval(
    console: Console,
    tool: str,
    arguments: dict[str, Any],
    *,
    diff: str = "",
    reason: str = "",
    policy: ApprovalPolicy | None = None,
) -> Decision:
    policy = policy or ApprovalPolicy()
    pattern = action_pattern(tool, arguments)
    if policy.remembered(pattern):
        return "allow"

    console.print(render_approval_panel(tool, arguments, diff=diff, reason=reason))
    try:
        choice = Prompt.ask(
            " ",
            choices=["a", "s", "p", "n", "q"],
            default="n",
            console=console,
            show_choices=False,
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "stop"

    if choice == "a":
        return "allow"
    if choice == "s":
        policy.remember(pattern, always=False)
        return "session"
    if choice == "p":
        policy.remember(pattern, always=True)
        return "always"
    if choice == "q":
        return "stop"
    return "deny"


def make_approver(
    console: Console,
    *,
    mode: AgentMode,
    approval: ApprovalMode,
    policy: ApprovalPolicy | None = None,
    interactive: bool = True,
    trusted_paths: list[str] | None = None,
    workspace_cwd: str | None = None,
) -> Callable[[str, dict[str, Any], dict[str, Any]], Decision]:
    """Returns a callback (tool, args, extra) -> Decision."""
    policy = policy or ApprovalPolicy.load()

    def approve(tool: str, arguments: dict[str, Any], extra: dict[str, Any] | None = None) -> Decision:
        extra = extra or {}
        if mode is AgentMode.PLAN and tool != "todo_write":
            return "deny"
        if approval is ApprovalMode.READONLY and tool in MUTATING_TOOLS:
            return "deny"
        if not needs_approval(
            tool,
            mode,
            approval,
            command=str(arguments.get("command") or ""),
            trusted_paths=trusted_paths,
            workspace_cwd=workspace_cwd,
            bash_cwd=str(arguments.get("cwd") or "") or None,
        ):
            return "allow"
        pattern = action_pattern(tool, arguments)
        if policy.remembered(pattern):
            return "allow"
        if not interactive:
            return "deny" if is_git_write(str(arguments.get("command") or "")) or approval is ApprovalMode.APPROVE else "allow"
        return prompt_approval(
            console,
            tool,
            arguments,
            diff=str(extra.get("diff") or ""),
            reason=str(extra.get("reason") or ""),
            policy=policy,
        )

    return approve
