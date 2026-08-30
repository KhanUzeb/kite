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
    resolve_in_workspace,
    workspace_root,
)

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|authorization)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|xox[baprs]-[a-zA-Z0-9-]{20,})\b"),
]


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    reason: str = ""
    rewritten_args: dict[str, Any] | None = None


class GuardrailPolicy:
    def __init__(self, config: GuardrailConfig, cwd: str | Path):
        self.config = config
        self.cwd = workspace_root(cwd)
        self._deny = [re.compile(p, re.IGNORECASE) for p in config.deny_bash_patterns]

    def check_path(self, path: str | Path, *, for_write: bool = False) -> GuardrailVerdict:
        if not self.config.enabled:
            return GuardrailVerdict(True)
        try:
            resolved = resolve_in_workspace(path, self.cwd)
        except OSError as e:
            return GuardrailVerdict(False, f"invalid path: {e}")

        if self.config.sandbox_to_cwd and not self.config.allow_paths_outside_cwd:
            if not is_inside(resolved, self.cwd):
                return GuardrailVerdict(
                    False,
                    f"path escapes workspace sandbox ({self.cwd}): {resolved}",
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
        if self.config.sandbox_to_cwd and not self.config.allow_paths_outside_cwd:
            escaped = check_command_paths(command, self.cwd)
            if escaped:
                return GuardrailVerdict(False, escaped)
        workdir, reason = clamp_cwd(cwd, self.cwd)
        if workdir is None:
            return GuardrailVerdict(False, reason)
        return GuardrailVerdict(True, rewritten_args={"cwd": str(workdir)})

    def redact_secrets(self, text: str) -> tuple[str, int]:
        """Return (redacted_text, count_of_redactions)."""
        if not text:
            return text, 0
        count = 0
        out = text
        for rx in SECRET_PATTERNS:
            new, n = rx.subn("[REDACTED_SECRET]", out)
            count += n
            out = new
        return out, count

    def check_tool_call(self, tool: str, arguments: dict[str, Any]) -> GuardrailVerdict:
        if not self.config.enabled:
            return GuardrailVerdict(True)
        args = dict(arguments)

        if tool in {"read", "write", "edit", "grep", "glob", "ls"}:
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
                args["cwd"] = str(self.cwd)
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
        if isinstance(out.get("error"), str):
            err, redacted = self.redact_secrets(out["error"])
            out["error"] = err
            if redacted:
                out["secrets_redacted"] = int(out.get("secrets_redacted") or 0) + redacted
        return out
