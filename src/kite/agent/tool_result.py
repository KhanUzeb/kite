"""Structured tool result contract — shared by model, UI, and audit layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Central output budget: normalize() caps oversized output here so no caller
#: silently drops context. Callers with a workspace (read/bash) may spill to
#: `.kite/spills/` first; this cap is the backstop for everything else.
MAX_OUTPUT_CHARS = 12_000
HEAD_CHARS = 8_000
TAIL_CHARS = 2_000


@dataclass(slots=True)
class ToolResult:
    ok: bool
    output: str = ""
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"ok": self.ok, "output": self.output}
        if self.summary:
            row["summary"] = self.summary
        if self.data:
            row.update(self.data)
        if self.warnings:
            row["warnings"] = list(self.warnings)
        if self.error:
            row["error"] = self.error
        if self.metadata:
            row["metadata"] = dict(self.metadata)
        return row

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ToolResult:
        reserved = {"ok", "output", "summary", "warnings", "error", "metadata"}
        data = {k: v for k, v in raw.items() if k not in reserved}
        return cls(
            ok=bool(raw.get("ok", True)),
            output=str(raw.get("output") or raw.get("error") or ""),
            summary=str(raw.get("summary") or ""),
            data=data,
            warnings=list(raw.get("warnings") or []),
            error=str(raw["error"]) if raw.get("error") else None,
            metadata=dict(raw.get("metadata") or {}),
        )

    @classmethod
    def normalize(cls, raw: dict[str, Any], *, tool: str | None = None, duration_ms: int | None = None, max_chars: int = MAX_OUTPUT_CHARS) -> dict[str, Any]:
        """Coerce a legacy tool dict into the standard observation shape.

        Oversized output is capped centrally (head + explicit marker + tail)
        so the model never silently loses context. The short summary is
        always kept visible alongside the cap.
        """
        result = cls.from_dict(raw)
        output = result.output or ""
        if len(output) > max_chars and max_chars > 0:
            head = max(0, min(HEAD_CHARS, max_chars - TAIL_CHARS - 200))
            tail = output[-TAIL_CHARS:] if TAIL_CHARS > 0 else ""
            omitted = len(output) - head - len(tail)
            marker = (
                f"\n...[truncated {omitted:,} of {len(output):,} chars; "
                f"showing head {head:,} + tail {len(tail):,}; "
                f"use read offset/limit or bash tail/grep for more]\n"
            )
            result.output = output[:head] + marker + tail
            note = f"output truncated: {omitted:,} of {len(output):,} chars capped"
            if note not in result.warnings:
                result.warnings.append(note)
            meta_trunc = dict(result.metadata)
            meta_trunc["truncated"] = True
            result.metadata = meta_trunc
        if not result.summary:
            preview = (output or result.error or "").strip().replace("\n", " ")
            result.summary = preview[:120]
        meta = dict(result.metadata)
        if tool and "tool" not in meta:
            meta["tool"] = tool
        if duration_ms is not None:
            meta["duration_ms"] = duration_ms
        result.metadata = meta
        return result.to_dict()
