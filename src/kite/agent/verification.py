"""Task verification collector — artifacts humans can check in <30s."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VerificationStatus = Literal["verified", "partial", "unverified", "failed"]


@dataclass
class Artifact:
    kind: str  # diff | test | command | screenshot | note
    summary: str
    path: str = ""
    ok: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "path": self.path,
            "ok": self.ok,
            "detail": self.detail[:500] if self.detail else "",
        }


@dataclass
class VerificationCollector:
    """Accumulates checkable evidence during a run."""

    artifacts: list[Artifact] = field(default_factory=list)
    last_bash_exit: int | None = None
    last_bash_command: str = ""
    diffs: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    _TEST_HINTS = ("pytest", "npm test", "pnpm test", "go test", "cargo test", "make test", "jest", "vitest", "ruff check", "uv run")

    def on_tool_end(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        if tool in {"write", "edit"} and result.get("ok"):
            path = str(result.get("path") or args.get("path") or "")
            diff = str(result.get("diff") or "")
            if diff:
                self.diffs.append(diff)
                self.artifacts.append(
                    Artifact(kind="diff", summary=f"edited {path}", path=path, ok=True, detail=diff[:400])
                )
        if tool == "bash":
            cmd = str(args.get("command") or "")
            self.last_bash_command = cmd
            rc = result.get("returncode")
            if rc is not None:
                self.last_bash_exit = int(rc)
            ok = bool(result.get("ok"))
            preview = (str(result.get("output") or "")[:200]).replace("\n", " ")
            self.artifacts.append(
                Artifact(
                    kind="command",
                    summary=cmd[:120],
                    ok=ok,
                    detail=preview,
                )
            )
            if any(h in cmd.lower() for h in self._TEST_HINTS):
                self.artifacts.append(
                    Artifact(
                        kind="test",
                        summary=f"exit={rc}  {cmd[:80]}",
                        ok=ok and rc == 0,
                        detail=preview,
                    )
                )
                if not ok or rc != 0:
                    self.gaps.append(f"test command failed (exit {rc}): {cmd[:80]}")

    def status(self) -> VerificationStatus:
        if self.gaps:
            return "failed"
        tests = [a for a in self.artifacts if a.kind == "test"]
        if tests and all(a.ok for a in tests):
            return "verified"
        if self.diffs or any(a.kind == "command" and a.ok for a in self.artifacts):
            return "partial"
        return "unverified"

    def summary(self) -> dict[str, Any]:
        st = self.status()
        return {
            "status": st,
            "artifact_count": len(self.artifacts),
            "diff_count": len(self.diffs),
            "gaps": list(self.gaps),
            "artifacts": [a.to_dict() for a in self.artifacts[-12:]],
            "last_bash_exit": self.last_bash_exit,
        }

    def render_lines(self) -> list[str]:
        st = self.status()
        lines = [f"verification: {st}"]
        for a in self.artifacts[-8:]:
            mark = "✓" if a.ok else "✗"
            lines.append(f"  {mark} [{a.kind}] {a.summary}")
        for g in self.gaps:
            lines.append(f"  ⚠ {g}")
        return lines
