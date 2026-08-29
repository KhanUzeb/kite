"""Permission gate with memory: once / session / always-this-pattern."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Literal

from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text

from kite.config import kite_home
from kite.agent.mode import MUTATING_TOOLS, AgentMode, ApprovalMode
from kite.ui.style import GUTTER, SYMBOL_WARN

Decision = Literal["allow", "session", "always", "deny", "stop"]


def action_pattern(tool: str, arguments: dict[str, Any]) -> str:
    """Stable pattern used for always-allow matching."""
    if tool == "bash":
        cmd = str(arguments.get("command") or "").strip()
        head = cmd.split()[0] if cmd else "*"
        return f"bash:{head}*"
    path = arguments.get("path") or arguments.get("root") or ""
    if path:
        return f"{tool}:{path}"
    return f"{tool}:*"


def needs_approval(tool: str, mode: AgentMode, approval: ApprovalMode, *, command: str = "") -> bool:
    if tool not in MUTATING_TOOLS:
        return False
    if mode is AgentMode.PLAN and tool != "todo_write":
        return True  # will be auto-denied by the agent; still surfaces
    if approval is ApprovalMode.READONLY:
        return True
    if approval is ApprovalMode.AUTO:
        return False
    if approval is ApprovalMode.TRUST:
        if tool != "bash":
            return False
        cmd = command.lower()
        destructive = any(
            tok in cmd
            for tok in ("rm -", "git push", "git reset", "chmod", "curl", "wget", "pip install", "npm install")
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
            if pattern == stored or fnmatch(pattern, stored):
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
) -> Callable[[str, dict[str, Any], dict[str, Any]], Decision]:
    """Returns a callback (tool, args, extra) -> Decision."""
    policy = policy or ApprovalPolicy.load()

    def approve(tool: str, arguments: dict[str, Any], extra: dict[str, Any] | None = None) -> Decision:
        extra = extra or {}
        if mode is AgentMode.PLAN and tool != "todo_write":
            return "deny"
        if approval is ApprovalMode.READONLY and tool in MUTATING_TOOLS:
            return "deny"
        if not needs_approval(tool, mode, approval, command=str(arguments.get("command") or "")):
            return "allow"
        pattern = action_pattern(tool, arguments)
        if policy.remembered(pattern):
            return "allow"
        if not interactive:
            # Non-TTY: fail closed on gated tools unless auto.
            return "deny" if approval is ApprovalMode.APPROVE else "allow"
        return prompt_approval(
            console,
            tool,
            arguments,
            diff=str(extra.get("diff") or ""),
            reason=str(extra.get("reason") or ""),
            policy=policy,
        )

    return approve
