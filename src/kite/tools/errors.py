"""Tool-error classification (§5): expected categories + per-tool/model rates.

Expected errors (invalid arguments, environment, provider, timeout, user
abort) are normal control flow. Unknown errors are harness bugs — track rates
per tool and per model so one focused effort can cut unexpected errors 10×.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

EXPECTED_CATEGORIES = (
    "invalid_arguments",
    "unexpected_environment",
    "provider_error",
    "timeout",
    "user_abort",
    "blocked",
)


def classify_tool_error(tool: str, args: dict[str, Any], out: dict[str, Any]) -> str:
    """Classify a failed tool result; `unknown` means a suspected harness bug."""
    if out.get("ok"):
        return "ok"
    if out.get("blocked") or out.get("status") == "denied":
        return "blocked"
    if out.get("cancelled"):
        return "user_abort"
    text = f"{out.get('error') or ''}\n{out.get('output') or ''}".lower()
    if "timeout after" in text or "timed out" in text:
        return "timeout"
    if any(s in text for s in ("not found", "no such file", "is a directory", "need name", "message required")):
        return "invalid_arguments"
    if any(s in text for s in ("connection", "provider", "rate limit", "overloaded", "unauthorized", "api key")):
        return "provider_error"
    if any(s in text for s in ("permission denied", "sandbox", "outside the workspace", "blocked in plan mode")):
        return "unexpected_environment"
    if tool in {"read", "grep", "glob", "ls"}:
        return "invalid_arguments"
    return "unknown"


@dataclass
class ToolErrorLedger:
    """Counts calls/errors per tool (+ per model) for baseline + validation."""

    calls: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)
    unexpected: Counter = field(default_factory=Counter)
    by_model: Counter = field(default_factory=Counter)

    def record(self, tool: str, out: dict[str, Any], *, model: str = "") -> str:
        category = classify_tool_error(tool, {}, out)
        self.calls[tool] += 1
        if model:
            self.by_model[f"{model}:{tool}"] += 1
        if category not in ("ok", "blocked"):
            self.errors[tool] += 1
        if category == "unknown":
            self.unexpected[tool] += 1
        return category

    def error_rate(self, tool: str) -> float:
        calls = max(1, self.calls.get(tool, 0))
        return self.errors.get(tool, 0) / calls

    def summary(self) -> dict[str, Any]:
        return {
            "calls": dict(self.calls),
            "errors": dict(self.errors),
            "unexpected": dict(self.unexpected),
            "by_model": dict(self.by_model),
        }
