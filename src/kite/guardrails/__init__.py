"""Guardrail policy — path sandbox, bash denylist, secret redaction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kite.config import GuardrailConfig

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|authorization)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|xox[baprs]-[a-zA-Z0-9-]{20,})\b"),
]

SENSITIVE_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "id_rsa", "id_ed25519"}


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    reason: str = ""
    rewritten_args: dict[str, Any] | None = None


class GuardrailPolicy:
    def __init__(self, config: GuardrailConfig, cwd: str | Path):
        self.config = config
        self.cwd = Path(cwd).expanduser().resolve()
        self._deny = [re.compile(p, re.IGNORECASE) for p in config.deny_bash_patterns]

    def check_path(self, path: str | Path, *, for_write: bool = False) -> GuardrailVerdict:
        if not self.config.enabled:
            return GuardrailVerdict(True)
        try:
            resolved = Path(path)
            if not resolved.is_absolute():
                resolved = (self.cwd / resolved).resolve()
            else:
                resolved = resolved.resolve()
        except OSError as e:
            return GuardrailVerdict(False, f"invalid path: {e}")

        if self.config.sandbox_to_cwd and not self.config.allow_paths_outside_cwd:
            try:
                resolved.relative_to(self.cwd)
            except ValueError:
                return GuardrailVerdict(
                    False,
                    f"path escapes workspace sandbox ({self.cwd}): {resolved}",
                )

        if for_write and self.config.block_secret_writes and resolved.name in SENSITIVE_NAMES:
            return GuardrailVerdict(False, f"refusing to write sensitive file: {resolved.name}")

        return GuardrailVerdict(True)

    def check_bash(self, command: str) -> GuardrailVerdict:
        if not self.config.enabled:
            return GuardrailVerdict(True)
        for rx in self._deny:
            if rx.search(command):
                return GuardrailVerdict(False, f"bash command blocked by guardrail pattern: {rx.pattern}")
        # soft-block reading .env via common patterns
        if re.search(r"(?i)(cat|type|Get-Content)\s+[^\n]*\.env\b", command):
            return GuardrailVerdict(False, "refusing to dump .env via bash; use careful read if needed")
        return GuardrailVerdict(True)

    def redact_secrets(self, text: str) -> str:
        if not text:
            return text
        out = text
        for rx in SECRET_PATTERNS:
            out = rx.sub("[REDACTED_SECRET]", out)
        return out

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
            return self.check_bash(str(args.get("command") or ""))

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
            text = self.redact_secrets(text)
            limit = self.config.max_bash_output_chars if tool == "bash" else self.config.max_read_chars
            if len(text) > limit:
                text = text[: limit // 2] + "\n...<guardrail truncated>...\n" + text[-(limit // 2) :]
                out["truncated"] = True
            out["output"] = text
        if isinstance(out.get("error"), str):
            out["error"] = self.redact_secrets(out["error"])
        return out
