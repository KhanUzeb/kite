"""Permission gate with memory: once / session / always-this-pattern."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from fnmatch import fnmatch
from typing import Any, Literal

from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text

from kite.agent.mode import MUTATING_TOOLS, READONLY_TOOLS, AgentMode, ApprovalMode
from kite.config import kite_home
from kite.guardrails.sandbox import (
    check_command_paths,
    check_dangerous,
    is_benign_cache_delete,
    is_inspection_bash,
    resolve_in_workspace,
    workspace_root,
)
from kite.ui.diff import count_diff_lines, diff_path, render_diff_stat
from kite.ui.style import GUTTER, PANEL_BAR
from kite.ui.tool_cards import render_bash_command_block

Decision = Literal["allow", "session", "always", "deny", "stop"]

GitBashKind = Literal["read", "write", "other"]


class ConsequenceLevel(IntEnum):
    """How serious a mutating action is — higher tiers prompt in more autonomy modes."""

    ROUTINE = 0   # in-workspace coding: install, test, edit, commit, rm, curl
    SERIOUS = 1   # durable memory, nested agents — prompt in trust/supervised
    CRITICAL = 2  # outside workspace, sudo, sandbox-blocked — prompt in auto; deny headless


# Never prompt via the approval gate (yolo defers to sandbox/guardrail deny rules).
_NEVER_PROMPT = ConsequenceLevel.CRITICAL + 1

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

# Critical bash — always prompt, even in yolo (outside-workspace / privileged / remote).
_CRITICAL_BASH = re.compile(
    r"(?i)\b("
    r"sudo\b|su\b|doas\b"
    r"|docker\s+(run|rm|system\s+prune)|kubectl\s+(apply|delete)"
    r"|ssh\b|scp\b|rsync\b"
    r")\b"
)

# Coding blanket — routine in-workspace dev commands (Codex workspace-write, OMP write mode).
_CODING_BASH = re.compile(
    r"(?i)(?:^|[;&|]\s*)("
    r"pip3?\b|npm\b|yarn\b|pnpm\b|cargo\b|uv\b|apt(?:-get)?\b|brew\b|dnf\b|yum\b"
    r"|pytest\b|jest\b|mocha\b|vitest\b|cargo\s+(test|build|run|check)\b|go\s+(test|build|run)\b"
    r"|make\b|cmake\b|ninja\b|gradle\b|mvn\b|npm\s+(test|run|start|ci)\b|yarn\s+(test|run)\b"
    r"|python3?\s+-m\s+(pytest|pip|build|unittest)\b|node\b|npx\b|uvicorn\b|gunicorn\b"
    r"|git\s+(status|diff|log|show|branch|add|commit|checkout|merge|pull|stash|switch|restore|rev-parse|describe|fetch)\b"
    r"|mkdir\b|touch\b|cp\b|mv\b|rm\b|rmdir\b|chmod\b|chown\b|cat\b|head\b|tail\b|tee\b"
    r"|curl\b|wget\b|rg\b|grep\b|find\b|fd\b|ls\b|pwd\b|echo\b|which\b|wc\b|file\b|stat\b|tree\b"
    r"|docker\s+compose\b|docker\s+build\b|kubectl\s+get\b|kubectl\s+describe\b"
    r")\b"
)


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


def _git_bash_consequence(command: str) -> ConsequenceLevel:
    """Classify git subcommands by consequence — commit/add/checkout are routine dev work."""
    tokens = _git_command_tokens(command)
    if not tokens:
        return ConsequenceLevel.ROUTINE
    sub, *rest = tokens
    if sub in {"push", "fetch"}:
        return ConsequenceLevel.SERIOUS
    if sub in {"reset", "rebase", "clean", "filter-branch", "update-ref"}:
        return ConsequenceLevel.SERIOUS
    if sub == "stash" and rest and rest[0] in {"pop", "apply", "drop", "clear", "push", "store"}:
        return ConsequenceLevel.SERIOUS
    if sub == "branch" and any(x in rest for x in ("-d", "-D", "-m", "-M", "--delete", "--move")):
        return ConsequenceLevel.SERIOUS
    if sub == "remote" and rest and rest[0] in {"add", "remove", "rm", "set-url", "rename", "prune"}:
        return ConsequenceLevel.SERIOUS
    if sub == "tag" and rest and not rest[0].startswith("-") and rest[0] not in {"-l", "--list", "list"}:
        return ConsequenceLevel.SERIOUS
    if sub == "config" and rest and rest[0] not in {"--get", "--list", "-l"} and not any(
        r.startswith("--get") for r in rest
    ):
        if len(rest) >= 2 or "=" in " ".join(rest):
            return ConsequenceLevel.SERIOUS
    return ConsequenceLevel.ROUTINE


def is_coding_bash(command: str) -> bool:
    """True when bash looks like routine in-workspace development work."""
    cmd = (command or "").strip()
    if not cmd or check_dangerous(cmd):
        return False
    if _CRITICAL_BASH.search(cmd):
        return False
    return bool(_CODING_BASH.search(cmd))


def _in_workspace_coding_blanket(
    cmd: str,
    *,
    workspace_cwd: str | None,
    bash_cwd: str | None,
) -> bool:
    """Codex workspace-write / OMP write-mode blanket: in-project coding auto-runs."""
    if not workspace_cwd or not _cwd_in_workspace(bash_cwd, workspace_cwd):
        return False
    if check_command_paths(cmd, workspace_root(workspace_cwd)):
        return False
    if is_benign_cache_delete(cmd):
        return True
    if is_git_read(cmd):
        return True
    if is_git_write(cmd) and _git_bash_consequence(cmd) is ConsequenceLevel.ROUTINE:
        return True
    return is_coding_bash(cmd)


def action_consequence(
    tool: str,
    *,
    command: str = "",
    arguments: dict[str, Any] | None = None,
    workspace_cwd: str | None = None,
    bash_cwd: str | None = None,
) -> tuple[ConsequenceLevel, str]:
    """Return (severity, reason). In-workspace coding is ROUTINE; only boundary escapes prompt in auto."""
    args = arguments or {}
    if tool in {"write", "edit"}:
        path = str(args.get("path") or "")
        if path and workspace_cwd and not _path_in_workspace(path, workspace_cwd):
            return ConsequenceLevel.CRITICAL, "writes outside the project workspace always need approval"
        return ConsequenceLevel.ROUTINE, ""
    if tool != "bash":
        return ConsequenceLevel.ROUTINE, ""
    cmd = (command or str(args.get("command") or "")).strip()
    if not cmd:
        return ConsequenceLevel.ROUTINE, ""
    blocked = check_dangerous(cmd)
    if blocked:
        reason = blocked.replace("bash command blocked by sandbox: ", "blocked command — ")
        return ConsequenceLevel.CRITICAL, reason
    if workspace_cwd and check_command_paths(cmd, workspace_root(workspace_cwd)):
        return ConsequenceLevel.CRITICAL, "shell paths outside the project workspace always need approval"
    if workspace_cwd and not _cwd_in_workspace(bash_cwd, workspace_cwd):
        return ConsequenceLevel.CRITICAL, "shell outside the project workspace always needs approval"
    if _CRITICAL_BASH.search(cmd):
        if re.search(r"(?i)\b(sudo|su|doas)\b", cmd):
            return ConsequenceLevel.CRITICAL, "privileged commands always need approval"
        return ConsequenceLevel.CRITICAL, "high-risk remote or privileged command always needs approval"
    if _in_workspace_coding_blanket(cmd, workspace_cwd=workspace_cwd, bash_cwd=bash_cwd):
        return ConsequenceLevel.ROUTINE, ""
    if is_git_write(cmd):
        level = _git_bash_consequence(cmd)
        if level is ConsequenceLevel.SERIOUS:
            return level, "git history or remote changes need approval"
    return ConsequenceLevel.ROUTINE, ""


def consequence_prompt_threshold(approval: ApprovalMode) -> int:
    """Minimum consequence level that triggers a prompt for this autonomy mode."""
    if approval is ApprovalMode.YOLO:
        return _NEVER_PROMPT
    if approval is ApprovalMode.AUTO:
        return ConsequenceLevel.CRITICAL
    if approval is ApprovalMode.TRUST:
        return ConsequenceLevel.SERIOUS
    if approval is ApprovalMode.APPROVE:
        return ConsequenceLevel.ROUTINE
    return ConsequenceLevel.ROUTINE


def mandatory_approval_reason(
    tool: str,
    *,
    command: str = "",
    arguments: dict[str, Any] | None = None,
    workspace_cwd: str | None = None,
    bash_cwd: str | None = None,
) -> str | None:
    """Return a reason only for critical-tier actions (always prompt, even in yolo)."""
    level, reason = action_consequence(
        tool,
        command=command,
        arguments=arguments,
        workspace_cwd=workspace_cwd,
        bash_cwd=bash_cwd,
    )
    if level is ConsequenceLevel.CRITICAL and reason:
        return reason
    return None


def is_mandatory_approval(
    tool: str,
    *,
    command: str = "",
    arguments: dict[str, Any] | None = None,
    workspace_cwd: str | None = None,
    bash_cwd: str | None = None,
) -> bool:
    level, _ = action_consequence(
        tool,
        command=command,
        arguments=arguments,
        workspace_cwd=workspace_cwd,
        bash_cwd=bash_cwd,
    )
    return level is ConsequenceLevel.CRITICAL


_SAFE_BASH = re.compile(
    r"(?i)^\s*("
    r"git\s+(status|diff|log|show|branch|stash\s+list)"
    r"|pytest\b|npm\s+test\b|cargo\s+test\b|go\s+test\b|make\s+test\b"
    r"|ls\b|cat\b|head\b|tail\b|rg\b|grep\b|find\b|pwd\b|echo\b|which\b"
    r"|node\s+--version|python3?\s+--version|uv\s+--version"
    r")\b"
)


def _is_safe_bash(command: str) -> bool:
    cmd = (command or "").strip()
    if not cmd:
        return True
    if is_git_write(cmd):
        return False
    return bool(_SAFE_BASH.match(cmd))


def _path_in_workspace(path: str, workspace_cwd: str | None) -> bool:
    if not path or not workspace_cwd:
        return True
    try:
        resolved = resolve_in_workspace(path, workspace_cwd)
        resolved.relative_to(workspace_root(workspace_cwd))
        return True
    except (ValueError, OSError):
        return False


def _cwd_in_workspace(bash_cwd: str | None, workspace_cwd: str | None) -> bool:
    """True when bash runs inside the project workspace (or cwd unset → workspace default)."""
    if not workspace_cwd:
        return True
    if not bash_cwd:
        return True
    return _path_in_workspace(bash_cwd, workspace_cwd)


def _needs_approval_plan(tool: str, mode: AgentMode, command: str) -> bool | None:
    if mode is not AgentMode.PLAN or tool == "todo_write":
        return None
    if tool == "bash" and is_inspection_bash(command):
        return False
    return True  # auto-denied by the agent; still surfaces in UI


def _needs_approval_auto(
    tool: str,
    args: dict[str, Any],
    *,
    workspace_cwd: str | None,
    bash_cwd: str | None,
) -> bool:
    if tool in {"write", "edit"}:
        path = str(args.get("path") or "")
        return not _path_in_workspace(path, workspace_cwd)
    if tool == "bash":
        return not _cwd_in_workspace(bash_cwd, workspace_cwd)
    return False


def _needs_approval_trust(
    tool: str,
    command: str,
    *,
    trusted_paths: list[str] | None,
    workspace_cwd: str | None,
    bash_cwd: str | None,
) -> bool:
    """Trust mode: coding blanket + trusted subtrees; prompts on serious non-coding effects."""
    if tool != "bash":
        return False
    if _in_workspace_coding_blanket(command, workspace_cwd=workspace_cwd, bash_cwd=bash_cwd):
        return False
    if trusted_paths and workspace_cwd:
        from kite.guardrails.sandbox import clamp_cwd, cwd_in_trusted, workspace_root

        root = workspace_root(workspace_cwd)
        workdir, _ = clamp_cwd(bash_cwd, root)
        if workdir and cwd_in_trusted(workdir, root, trusted_paths) and _is_safe_bash(command):
            return False
    if _cwd_in_workspace(bash_cwd, workspace_cwd) and _is_safe_bash(command):
        return False
    return True


def _needs_approval_by_mode(
    tool: str,
    approval: ApprovalMode,
    *,
    command: str,
    args: dict[str, Any],
    trusted_paths: list[str] | None,
    workspace_cwd: str | None,
    bash_cwd: str | None,
) -> bool | None:
    if approval is ApprovalMode.READONLY:
        return True
    if approval is ApprovalMode.YOLO:
        return False
    if approval is ApprovalMode.AUTO:
        return _needs_approval_auto(tool, args, workspace_cwd=workspace_cwd, bash_cwd=bash_cwd)
    if approval is ApprovalMode.APPROVE:
        return True
    if approval is ApprovalMode.TRUST:
        return _needs_approval_trust(
            tool,
            command,
            trusted_paths=trusted_paths,
            workspace_cwd=workspace_cwd,
            bash_cwd=bash_cwd,
        )
    return None


def _effect_consequence(
    effects: tuple[str, ...],
    *,
    tool: str,
    args: dict[str, Any],
) -> tuple[ConsequenceLevel, str]:
    """Map canonical tool effects to consequence tiers."""
    from kite.application.tools import mandatory_reason as canonical_mandatory_reason

    reason = canonical_mandatory_reason(effects, tool=tool, args=args)
    if not reason:
        return ConsequenceLevel.ROUTINE, ""
    low = reason.lower()
    if "outside" in low or "privileged" in low or "blocked" in low:
        return ConsequenceLevel.CRITICAL, reason
    if "package" in low or "skill install" in low or "network" in low or "destructive" in low:
        return ConsequenceLevel.ROUTINE, ""
    if "nested agent" in low or "durable memory" in low:
        return ConsequenceLevel.SERIOUS, reason
    return ConsequenceLevel.SERIOUS, reason


def needs_approval(
    tool: str,
    mode: AgentMode,
    approval: ApprovalMode,
    *,
    command: str = "",
    arguments: dict[str, Any] | None = None,
    trusted_paths: list[str] | None = None,
    workspace_cwd: str | None = None,
    bash_cwd: str | None = None,
    effects: tuple[str, ...] | None = None,
) -> bool:
    args = arguments or {}
    if tool not in MUTATING_TOOLS:
        if effects:
            level, _ = _effect_consequence(effects, tool=tool, args=args)
            return level >= consequence_prompt_threshold(approval)
        return False
    if tool == "bash" and (is_git_read(command) or is_inspection_bash(command)):
        return False
    plan = _needs_approval_plan(tool, mode, command)
    if plan is not None:
        return plan
    if approval is ApprovalMode.READONLY:
        return True
    level, _ = action_consequence(
        tool,
        command=command,
        arguments=args,
        workspace_cwd=workspace_cwd,
        bash_cwd=bash_cwd,
    )
    if effects:
        effect_level, _ = _effect_consequence(effects, tool=tool, args=args)
        level = max(level, effect_level, key=int)
    if approval is ApprovalMode.TRUST and tool == "bash":
        if trusted_paths and workspace_cwd:
            from kite.guardrails.sandbox import clamp_cwd, cwd_in_trusted, workspace_root

            root = workspace_root(workspace_cwd)
            workdir, _ = clamp_cwd(bash_cwd, root)
            if workdir and cwd_in_trusted(workdir, root, trusted_paths) and _is_safe_bash(command):
                return False
        if _cwd_in_workspace(bash_cwd, workspace_cwd) and _is_safe_bash(command):
            return False
    threshold = consequence_prompt_threshold(approval)
    return level >= threshold


_GIT_WRITE_BASH = re.compile(r"(?i)bash:git\s+(commit|push|reset|rebase)")
_GIT_WRITE_STORED = re.compile(r"(?i)git\s+(commit|push|reset|rebase)")


def _fnmatch_git_write_overbroad(pattern: str, stored: str) -> bool:
    return bool(_GIT_WRITE_BASH.search(pattern) and not _GIT_WRITE_STORED.search(stored))


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
        from kite.memory.session_policy import secure_session_file

        secure_session_file(path)

    def remembered(self, pattern: str) -> bool:
        if pattern in self.always_patterns or pattern in self.session_patterns:
            return True
        for stored in (*self.always_patterns, *self.session_patterns):
            if pattern != stored and not fnmatch(pattern, stored):
                continue
            if _fnmatch_git_write_overbroad(pattern, stored):
                continue
            return True
        return False

    def remember(self, pattern: str, *, always: bool) -> None:
        if always:
            self.always_patterns.add(pattern)
            self.save()
        else:
            self.session_patterns.add(pattern)


APPROVAL_BAR = PANEL_BAR


def render_approval_panel(
    tool: str,
    arguments: dict[str, Any],
    *,
    diff: str = "",
    reason: str = "",
    mandatory: bool = False,
) -> Text:
    """Permission gate — left-bar layout, no duplicate waiting line elsewhere."""
    body = Text()
    body.append(f"{GUTTER}{APPROVAL_BAR}", style="kite.pending")
    body.append("approve ", style="kite.pending")
    body.append(tool, style="kite.tool bold")
    if mandatory:
        body.append("  mandatory", style="kite.error")
    body.append("\n")

    if reason:
        body.append(f"{GUTTER}{APPROVAL_BAR}", style="kite.muted")
        body.append(reason.strip(), style="kite.muted")
        body.append("\n")

    if tool == "bash":
        cmd = str(arguments.get("command") or "").strip()
        cwd = arguments.get("cwd")
        body.append_text(render_bash_command_block(cmd, max_lines=6))
        if cwd:
            body.append(f"{GUTTER}{APPROVAL_BAR}", style="kite.muted")
            body.append(f"cwd  {cwd}\n", style="kite.terminal")
    else:
        for key in ("path", "root", "pattern", "query"):
            if arguments.get(key):
                body.append(f"{GUTTER}{APPROVAL_BAR}", style="kite.muted")
                body.append(f"{key}  ", style="kite.muted")
                body.append(f"{arguments[key]}\n", style="kite.terminal")
        if diff:
            added, deleted = count_diff_lines(diff)
            if added or deleted:
                body.append(f"{GUTTER}{APPROVAL_BAR}")
                body.append_text(render_diff_stat(added, deleted, path=diff_path(diff)))
                body.append("\n")
            preview = "\n".join(diff.splitlines()[:40])
            for line in preview.splitlines():
                if line.startswith("+++") or line.startswith("---"):
                    style = "kite.diff.meta"
                elif line.startswith("+"):
                    style = "kite.diff.add"
                elif line.startswith("-"):
                    style = "kite.diff.del"
                elif line.startswith("@@"):
                    style = "kite.diff.hunk"
                elif line.startswith(" ") or not line:
                    style = "kite.diff.ctx"
                else:
                    style = "kite.diff.meta"
                body.append(f"{GUTTER}{APPROVAL_BAR}", style="kite.muted")
                body.append(line + "\n", style=style)
            extra = max(0, len(diff.splitlines()) - 40)
            if extra:
                body.append(f"{GUTTER}{APPROVAL_BAR}… {extra} more diff lines\n", style="kite.muted")

    body.append(f"{GUTTER}{APPROVAL_BAR}\n", style="kite.muted")
    body.append(f"{GUTTER}{APPROVAL_BAR}", style="kite.muted")
    body.append("[a]", style="kite.success")
    body.append(" once  ", style="kite.muted")
    if not mandatory:
        body.append("[s]", style="kite.success")
        body.append(" session  ", style="kite.muted")
        body.append("[p]", style="kite.success")
        body.append(" always  ", style="kite.muted")
    body.append("[n]", style="kite.pending")
    body.append(" deny  ", style="kite.muted")
    body.append("[q]", style="kite.error")
    body.append(" stop\n", style="kite.muted")
    return body


def prompt_approval(
    console: Console,
    tool: str,
    arguments: dict[str, Any],
    *,
    diff: str = "",
    reason: str = "",
    policy: ApprovalPolicy | None = None,
    mandatory: bool = False,
) -> Decision:
    policy = policy or ApprovalPolicy()
    pattern = action_pattern(tool, arguments)
    if not mandatory and policy.remembered(pattern):
        return "allow"

    console.print(render_approval_panel(tool, arguments, diff=diff, reason=reason, mandatory=mandatory))
    choices = ["a", "n", "q"] if mandatory else ["a", "s", "p", "n", "q"]
    try:
        choice = Prompt.ask(
            " ",
            choices=choices,
            default="n",
            console=console,
            show_choices=False,
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "stop"

    if choice == "a":
        return "allow"
    if not mandatory and choice == "s":
        policy.remember(pattern, always=False)
        return "session"
    if not mandatory and choice == "p":
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
    coordinator: Any | None = None,
) -> Callable[[str, dict[str, Any], dict[str, Any]], Decision]:
    """Returns a callback (tool, args, extra) -> Decision."""
    policy = policy or ApprovalPolicy.load()

    def _prompt_or_coordinate(
        tool: str,
        arguments: dict[str, Any],
        extra: dict[str, Any],
        *,
        reason: str,
        mandatory: bool,
    ) -> Decision:
        diff = str(extra.get("diff") or "")
        if coordinator is not None:
            return coordinator.request(
                tool,
                arguments,
                reason=reason,
                mandatory=mandatory,
                diff=diff,
                extra=extra,
            )
        if not interactive:
            return "deny"
        return prompt_approval(
            console,
            tool,
            arguments,
            diff=diff,
            reason=reason,
            policy=policy,
            mandatory=mandatory,
        )

    def approve(tool: str, arguments: dict[str, Any], extra: dict[str, Any] | None = None) -> Decision:
        from kite.application.tools import ToolCall, derive_effects

        extra = extra or {}
        cmd = str(arguments.get("command") or "")
        bash_cwd = str(arguments.get("cwd") or "") or None
        effects = tuple(derive_effects(ToolCall("approval", tool, arguments)))
        level, reason = action_consequence(
            tool,
            command=cmd,
            arguments=arguments,
            workspace_cwd=workspace_cwd,
            bash_cwd=bash_cwd,
        )
        effect_level, effect_reason = _effect_consequence(effects, tool=tool, args=arguments)
        if tool == "bash" and level is ConsequenceLevel.ROUTINE:
            reason = reason or effect_reason
        else:
            level = max(level, effect_level, key=int)
            reason = reason or effect_reason
        mutates = bool(
            set(effects) & {"durable_memory", "destructive", "package_or_skill_install"}
            or tool in MUTATING_TOOLS
            or (
                "workspace_write" in effects
                and tool not in READONLY_TOOLS
                and tool not in {"submit", "todo_write"}
            )
        )
        if mode is AgentMode.PLAN and tool != "todo_write":
            if tool == "bash" and is_inspection_bash(cmd):
                return "allow"
            if mutates:
                return "deny"
        if approval is ApprovalMode.READONLY and mutates:
            return "deny"
        threshold = consequence_prompt_threshold(approval)
        if level < threshold:
            return "allow"
        if not needs_approval(
            tool,
            mode,
            approval,
            command=cmd,
            arguments=arguments,
            trusted_paths=trusted_paths,
            workspace_cwd=workspace_cwd,
            bash_cwd=bash_cwd,
            effects=effects,
        ):
            return "allow"
        pattern = action_pattern(tool, arguments)
        if policy.remembered(pattern) and level < ConsequenceLevel.CRITICAL:
            return "allow"
        if not interactive:
            return "deny" if level >= threshold else "allow"
        return _prompt_or_coordinate(
            tool,
            arguments,
            extra,
            reason=reason or str(extra.get("reason") or ""),
            mandatory=level >= ConsequenceLevel.CRITICAL,
        )

    return approve
