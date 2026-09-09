"""Policy engine — authorize tool intents and path containment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kite.application.tools.contracts import PolicyDecision, ToolCall, ToolIntent
from kite.application.tools.effects import MANDATORY_EFFECTS, derive_effects, mandatory_reason
from kite.guardrails.sandbox import check_command_paths, is_inside, protected_roots, resolve_in_workspace

POLICY_VERSION = "0.9.0"


def _is_sibling_prefix(resolved: Path, root: Path) -> bool:
    root_s, res_s = str(root), str(resolved)
    if res_s == root_s or not res_s.startswith(root_s):
        return False
    return res_s[len(root_s)] not in "\\/"


def check_path_access(
    path: str | Path,
    workspace: str | Path,
    *,
    write: bool = False,
    execution_mode: str = "restricted",
) -> tuple[bool, str]:
    """Return (allowed, reason). Host skips workspace clamp; protected paths always blocked."""
    root = Path(workspace).expanduser().resolve()
    try:
        resolved = resolve_in_workspace(path, root)
    except Exception as exc:
        return False, str(exc)
    if _is_sibling_prefix(resolved, root):
        return False, "sibling-prefix escape"
    for prot in protected_roots():
        try:
            if resolved == prot.resolve() or resolved.is_relative_to(prot.resolve()):
                return False, f"protected path: {resolved}"
        except (ValueError, OSError):
            continue
    if execution_mode != "host" and not is_inside(resolved, root):
        return False, f"path outside workspace: {resolved}"
    return True, "ok"


class PolicyEngine:
    """Pure authorization seam — no UI, no execution."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        execution_mode: str = "restricted",
        no_guardrails: bool = False,
    ) -> None:
        self.workspace = str(Path(workspace).expanduser().resolve())
        self.execution_mode = execution_mode or "restricted"
        self.no_guardrails = no_guardrails
        self.policy_version = POLICY_VERSION

    def derive_intent(self, call: ToolCall) -> ToolIntent:
        effects = derive_effects(call)
        targets: list[str] = []
        args = dict(call.arguments)
        for key in ("path", "file_path", "target", "command"):
            if key in args and args[key]:
                targets.append(str(args[key]))
        cmd_digest = ""
        if "command" in args:
            cmd_digest = hashlib.sha256(str(args["command"]).encode()).hexdigest()[:16]
        content_digest = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
        return ToolIntent(
            tool=call.name,
            normalized_arguments=args,
            canonical_targets=tuple(targets),
            side_effects=effects,
            workspace=self.workspace,
            command_digest=cmd_digest,
            content_digest=content_digest,
        )

    def authorize(self, intent: ToolIntent) -> PolicyDecision:
        mandatory = mandatory_reason(
            intent.side_effects,
            tool=intent.tool,
            args=intent.normalized_arguments,
        )
        if self.no_guardrails:
            return PolicyDecision(
                allowed=True,
                reason="guardrails disabled",
                requires_approval=True,
                mandatory=bool(mandatory),
                policy_version=self.policy_version,
                scope="global",
            )

        if self.execution_mode == "restricted" and "network" in intent.side_effects:
            if intent.tool in {
                "bash",
                "webfetch",
                "websearch",
                "webcrawl",
                "web_fetch",
                "web_search",
                "context7_resolve",
                "context7_docs",
            }:
                return PolicyDecision(
                    allowed=False,
                    reason="network access blocked in restricted mode",
                    policy_version=self.policy_version,
                )

        for target in intent.canonical_targets:
            if intent.tool in ("read", "write", "edit", "grep", "glob", "ls", "apply_patch") or "path" in intent.normalized_arguments:
                write = intent.tool in ("write", "edit", "apply_patch")
                ok, reason = check_path_access(
                    target,
                    self.workspace,
                    write=write,
                    execution_mode=self.execution_mode,
                )
                if not ok:
                    return PolicyDecision(allowed=False, reason=reason, policy_version=self.policy_version)

        if intent.tool == "bash" and self.execution_mode != "host":
            cmd = str(intent.normalized_arguments.get("command") or "")
            escaped = check_command_paths(cmd, Path(self.workspace))
            if escaped:
                return PolicyDecision(allowed=False, reason=escaped, policy_version=self.policy_version)
            cwd = intent.normalized_arguments.get("cwd")
            if cwd:
                ok, reason = check_path_access(str(cwd), self.workspace, execution_mode=self.execution_mode)
                if not ok:
                    return PolicyDecision(allowed=False, reason=reason, policy_version=self.policy_version)

        if intent.tool == "skill" and intent.normalized_arguments.get("install"):
            return PolicyDecision(
                allowed=False,
                reason="skill install must go through approval pipeline",
                policy_version=self.policy_version,
            )

        requires_approval = any(e in intent.side_effects for e in MANDATORY_EFFECTS) or any(
            e in intent.side_effects for e in ("workspace_write", "long_running")
        )
        return PolicyDecision(
            allowed=True,
            requires_approval=requires_approval,
            mandatory=bool(mandatory),
            reason=mandatory or "",
            policy_version=self.policy_version,
            scope=intent.tool,
        )
