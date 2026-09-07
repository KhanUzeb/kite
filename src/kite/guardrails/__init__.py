"""Guardrail policy — path sandbox, bash denylist, secret redaction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kite.config import GuardrailConfig
from kite.guardrails.sandbox import (
    SENSITIVE_NAMES,
    check_command_paths,
    check_dangerous,
    clamp_cwd,
    is_inside,
    is_protected,
    is_user_skill_read,
    resolve_in_workspace,
    workspace_root,
)

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|authorization)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|xox[baprs]-[a-zA-Z0-9-]{20,})\b"),
    re.compile(r"(?i)(?:key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9+/]{24,}={0,2}"),
]

_ENV_DUMP_PATTERNS = (
    re.compile(r"(?i)^\s*env\s*$"),
    re.compile(r"(?i)^\s*printenv\b"),
    re.compile(r"(?i)^\s*export\s*$"),
    re.compile(r"(?i)^\s*set\s*$"),
    re.compile(r"(?i)(Get-ChildItem|gci)\s+Env:"),
    re.compile(r"(?i)\bdir\s+env:"),
)

_CHAIN_SPLIT = re.compile(r"\s*&&\s*|\s*;\s*|\s*\|\s*")


def redact_secrets(text: str) -> tuple[str, int]:
    """Return (redacted_text, count_of_redactions). Usable without a policy instance."""
    if not text:
        return text, 0
    count = 0
    out = text
    for rx in SECRET_PATTERNS:
        new, n = rx.subn("[REDACTED_SECRET]", out)
        count += n
        out = new
    return out, count


def env_dump_blocked(command: str) -> str:
    """Non-empty reason when bash would dump the process environment."""
    segments = _CHAIN_SPLIT.split(command) if command else []
    if not segments:
        segments = [command]
    for segment in segments:
        for line in segment.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for rx in _ENV_DUMP_PATTERNS:
                if rx.search(stripped):
                    return "refusing to dump process environment via bash"
    return ""


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    reason: str = ""
    rewritten_args: dict[str, Any] | None = None


class GuardrailPolicy:
    def __init__(self, config: GuardrailConfig, cwd: str | Path, execution=None):
        self.config = config
        self.cwd = workspace_root(cwd)
        self.execution = execution
        self._deny = [re.compile(p, re.IGNORECASE) for p in config.deny_bash_patterns]

    @property
    def workspace(self) -> Path:
        if self.execution is not None:
            return workspace_root(self.execution.execution_cwd)
        return self.cwd

    def check_path(self, path: str | Path, *, for_write: bool = False) -> GuardrailVerdict:
        if not self.config.enabled:
            return GuardrailVerdict(True)
        try:
            resolved = resolve_in_workspace(path, self.workspace)
        except OSError as e:
            return GuardrailVerdict(False, f"invalid path: {e}")

        if self.config.sandbox_to_cwd and not self.config.host_access():
            if not is_inside(resolved, self.workspace):
                if for_write or not is_user_skill_read(resolved):
                    return GuardrailVerdict(
                        False,
                        f"path escapes workspace sandbox ({self.workspace}): {resolved}",
                    )

        if is_protected(resolved):
            kind = "write" if for_write else "touch"
            return GuardrailVerdict(False, f"refusing to {kind} protected path: {resolved}")

        if for_write and self.config.block_secret_writes and resolved.name in SENSITIVE_NAMES:
            return GuardrailVerdict(False, f"refusing to write sensitive file: {resolved.name}")

        return GuardrailVerdict(True)

    def check_bash(self, command: str, *, cwd: str | None = None) -> GuardrailVerdict:
        if not self.config.enabled:
            return GuardrailVerdict(True)
        dangerous = check_dangerous(command)
        if dangerous:
            return GuardrailVerdict(False, dangerous)
        for rx in self._deny:
            if rx.search(command):
                return GuardrailVerdict(False, f"bash command blocked by guardrail pattern: {rx.pattern}")
        if re.search(r"(?i)(cat|type|Get-Content)\s+[^\n]*\.env\b", command):
            return GuardrailVerdict(False, "refusing to dump .env via bash; use careful read if needed")
        blocked = env_dump_blocked(command)
        if blocked:
            return GuardrailVerdict(False, blocked)
        if self.config.sandbox_to_cwd and not self.config.host_access():
            escaped = check_command_paths(command, self.workspace)
            if escaped:
                return GuardrailVerdict(False, escaped)
        workdir, reason = clamp_cwd(cwd, self.workspace, allow_outside=self.config.host_access())
        if workdir is None:
            return GuardrailVerdict(False, reason)
        return GuardrailVerdict(True, rewritten_args={"cwd": str(workdir)})

    def redact_secrets(self, text: str) -> tuple[str, int]:
        """Return (redacted_text, count_of_redactions)."""
        return redact_secrets(text)

    def check_set_cwd(self, path: str) -> GuardrailVerdict:
        """Allow set_cwd outside project root; sandbox follows the new execution cwd."""
        if not self.config.enabled:
            return GuardrailVerdict(True)
        token = str(path or "").strip()
        if not token:
            return GuardrailVerdict(False, "path required")
        try:
            if self.execution is not None:
                resolved = self.execution.resolve_path(token)
            else:
                resolved = resolve_in_workspace(token, self.cwd)
        except OSError as e:
            return GuardrailVerdict(False, f"invalid path: {e}")
        if is_protected(resolved):
            return GuardrailVerdict(False, f"refusing to set cwd to protected path: {resolved}")
        return GuardrailVerdict(True)

    def check_tool_call(self, tool: str, arguments: dict[str, Any]) -> GuardrailVerdict:
        if not self.config.enabled:
            return GuardrailVerdict(True)
        args = dict(arguments)

        if tool in {"read", "write", "edit", "grep", "glob", "ls", "task"}:
            path_key = "path" if "path" in args else ("root" if "root" in args else None)
            if path_key and args.get(path_key):
                v = self.check_path(str(args[path_key]), for_write=tool in {"write", "edit"})
                if not v.allowed:
                    return v
            if tool == "glob" and args.get("root"):
                v = self.check_path(str(args["root"]))
                if not v.allowed:
                    return v

        if tool == "bash":
            v = self.check_bash(str(args.get("command") or ""), cwd=str(args.get("cwd") or "") or None)
            if not v.allowed:
                return v
            if v.rewritten_args:
                args.update(v.rewritten_args)
            else:
                args["cwd"] = str(self.workspace)
            return GuardrailVerdict(True, rewritten_args=args)

        if tool == "set_cwd":
            v = self.check_set_cwd(str(args.get("path") or ""))
            if not v.allowed:
                return v
            return GuardrailVerdict(True, rewritten_args=args)

        if tool == "write" and self.config.block_secret_writes:
            content = str(args.get("content") or "")
            for rx in SECRET_PATTERNS:
                if rx.search(content):
                    return GuardrailVerdict(False, "refusing to write content that looks like a secret")

        return GuardrailVerdict(True, rewritten_args=args)

    def clamp_output(self, tool: str, result: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            return result
        out = dict(result)
        text = out.get("output")
        if isinstance(text, str):
            text, redacted = self.redact_secrets(text)
            if redacted:
                out["secrets_redacted"] = redacted
            limit = self.config.max_bash_output_chars if tool == "bash" else self.config.max_read_chars
            if len(text) > limit:
                text = text[: limit // 2] + "\n...<guardrail truncated>...\n" + text[-(limit // 2) :]
                out["truncated"] = True
            out["output"] = text
        for key in ("error", "diff", "path", "directory", "summary"):
            val = out.get(key)
            if isinstance(val, str):
                redacted_text, n = self.redact_secrets(val)
                out[key] = redacted_text
                if n:
                    out["secrets_redacted"] = int(out.get("secrets_redacted") or 0) + n
        items = out.get("items")
        if isinstance(items, list):
            safe_items: list[Any] = []
            total_redacted = int(out.get("secrets_redacted") or 0)
            for item in items:
                if isinstance(item, str):
                    safe, n = self.redact_secrets(item)
                    total_redacted += n
                    safe_items.append(safe)
                elif isinstance(item, dict):
                    safe_item = dict(item)
                    for ik, iv in list(safe_item.items()):
                        if isinstance(iv, str):
                            safe_item[ik], n = self.redact_secrets(iv)
                            total_redacted += n
                    safe_items.append(safe_item)
                else:
                    safe_items.append(item)
            out["items"] = safe_items
            if total_redacted:
                out["secrets_redacted"] = total_redacted
        metadata = out.get("metadata")
        if isinstance(metadata, dict):
            safe_meta = dict(metadata)
            total_redacted = int(out.get("secrets_redacted") or 0)
            for mk, mv in list(safe_meta.items()):
                if isinstance(mv, str):
                    safe_meta[mk], n = self.redact_secrets(mv)
                    total_redacted += n
            out["metadata"] = safe_meta
            if total_redacted:
                out["secrets_redacted"] = total_redacted
        return out
