"""Task verification collector — artifacts humans can check in <30s."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

VerificationStatus = Literal["verified", "partial", "unverified", "failed", "idle"]

# Explicit test/build/lint success — needs a recorded passing check, not `ls`.
_EVIDENCE_CLAIM_RE = re.compile(
    r"\b("
    r"tests?\s+pass(?:ed|ing)?|all\s+tests?\s+pass|"
    r"build\s+succeeds?|lint\s+clean|no\s+errors?|"
    r"fully\s+verified|confirmed\s+working|everything\s+works"
    r")\b",
    re.IGNORECASE,
)
# Narrated completion without evidence. Keep "all done" out — casual chat uses it.
_DONE_CLAIM_RE = re.compile(
    r"\b("
    r"task\s+complete|i(?:'ve| have)?\s+finished|"
    r"should\s+(?:work|pass)|looks\s+(?:good|fine)|"
    r"we(?:'re| are)\s+done|successfully\s+(?:implemented|fixed|completed)|"
    r"fully\s+implemented|all\s+good"
    r")\b",
    re.IGNORECASE,
)
_TEST_GAP_PREFIX = "test command failed"


@dataclass
class Artifact:
    kind: str  # diff | test | command | read | screenshot | note
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
    paths_touched: set[str] = field(default_factory=set)
    paths_read: set[str] = field(default_factory=set)

    _TEST_HINTS = (
        "pytest",
        "python -m pytest",
        "python -m unittest",
        "npm test",
        "npm run test",
        "pnpm test",
        "yarn test",
        "go test",
        "cargo test",
        "make test",
        "make check",
        "jest",
        "vitest",
        "ruff check",
        "mypy",
        "tox",
        "hatch test",
        "uv run pytest",
        "uv run test",
        "uv run ruff",
    )

    def on_tool_end(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        if tool in {"write", "edit"} and result.get("ok"):
            path = str(result.get("path") or args.get("path") or "")
            diff = str(result.get("diff") or "")
            if path:
                self.paths_touched.add(path)
            if diff:
                self.diffs.append(diff)
                self._add("diff", f"edited {path}", path=path, ok=True, detail=diff[:400])
        if tool == "read" and result.get("ok"):
            path = str(result.get("path") or args.get("path") or "")
            if path:
                self.paths_read.add(path)
                self._add("read", f"read {path}", path=path, ok=True)
        if tool == "bash":
            cmd = str(args.get("command") or "")
            self.last_bash_command = cmd
            rc = result.get("returncode")
            if rc is not None:
                self.last_bash_exit = int(rc)
            ok = bool(result.get("ok"))
            preview = (str(result.get("output") or "")[:200]).replace("\n", " ")
            self._add("command", cmd[:120], ok=ok, detail=preview)
            if self._looks_like_test(cmd):
                passed = ok and rc == 0
                self._add("test", f"exit={rc}  {cmd[:80]}", ok=passed, detail=preview)
                if passed:
                    self.gaps = [g for g in self.gaps if not g.startswith(_TEST_GAP_PREFIX)]
                else:
                    self.gaps.append(f"{_TEST_GAP_PREFIX} (exit {rc}): {cmd[:80]}")

    def _looks_like_test(self, cmd: str) -> bool:
        lowered = cmd.lower()
        return any(h in lowered for h in self._TEST_HINTS)

    def _add(self, kind: str, summary: str, **kw: Any) -> None:
        self.artifacts.append(Artifact(kind=kind, summary=summary, **kw))

    def has_edits(self) -> bool:
        return bool(self.diffs or self.paths_touched)

    def _latest_test(self) -> Artifact | None:
        tests = [a for a in self.artifacts if a.kind == "test"]
        return tests[-1] if tests else None

    def has_passing_tests(self) -> bool:
        latest = self._latest_test()
        return latest is not None and latest.ok

    def needs_tests(self) -> bool:
        return self.has_edits() and not self.has_passing_tests()

    def status(self) -> VerificationStatus:
        latest = self._latest_test()
        if latest is not None and not latest.ok:
            return "failed"
        if self.gaps:
            return "failed"
        if latest is not None and latest.ok:
            return "verified"
        if self.diffs or any(a.kind == "command" and a.ok for a in self.artifacts):
            return "partial"
        if self.artifacts:
            return "unverified"
        return "idle"

    def unfounded_claim_reason(self, text: str) -> str | None:
        """Block narrated success that is not backed by a recorded passing check."""
        body = (text or "").strip()
        if not body:
            return None
        if _EVIDENCE_CLAIM_RE.search(body) and not self.has_passing_tests():
            return (
                "Submit blocked: summary claims tests/build passed but no passing verification command "
                "was recorded in this session. Run the check first, then cite its output."
            )
        if _DONE_CLAIM_RE.search(body) and not self.has_passing_tests():
            if self.has_edits():
                return (
                    "Submit blocked: workspace was edited but no passing test/lint command was recorded. "
                    "Run pytest, ruff, npm test, or your project's check command, then submit again."
                )
            return (
                "Do not claim the task is done. No edits or verification were recorded this session. "
                "Use tools, then submit with evidence — do not narrate completion."
            )
        return None

    def has_work(self) -> bool:
        return bool(self.artifacts or self.diffs or self.gaps)

    def submit_block_reason(
        self,
        submission: str = "",
        *,
        require_verification: bool = True,
        require_verification_section: bool = True,
    ) -> str | None:
        """Return a human-readable reason when submit should be rejected."""
        if not require_verification:
            return None
        st = self.status()
        if st == "failed":
            gap = self.gaps[0] if self.gaps else "a test or check failed"
            return f"Submit blocked: {gap}. Fix the failure and re-run verification before submitting."

        body = (submission or "").strip()
        if self.has_edits() and not self.has_passing_tests():
            return (
                "Submit blocked: workspace was edited but no passing test/lint command was recorded. "
                "Run pytest, ruff, npm test, or your project's check command, then submit again."
            )

        claim = self.unfounded_claim_reason(body)
        if claim:
            return claim

        if require_verification_section and self.has_edits() and body:
            if "## verification" not in body.lower():
                return (
                    "Submit blocked: include a ## Verification section listing commands you ran "
                    "(e.g. `- ✓ pytest -q`). Do not claim done without checkable evidence."
                )
            if not re.search(r"[-*]\s*✓", body):
                return (
                    "Submit blocked: ## Verification must list at least one checked item "
                    "(e.g. `- ✓ pytest -q — 42 passed`)."
                )

        return None

    def post_edit_nudge(self) -> str | None:
        if not self.needs_tests():
            return None
        return (
            "[verification] Edits recorded — run your project's test or lint command "
            "and include the result before submitting."
        )

    def summary(self) -> dict[str, Any]:
        st = self.status()
        return {
            "status": st,
            "artifact_count": len(self.artifacts),
            "diff_count": len(self.diffs),
            "gaps": list(self.gaps),
            "artifacts": [a.to_dict() for a in self.artifacts[-12:]],
            "last_bash_exit": self.last_bash_exit,
            "paths_touched": sorted(self.paths_touched)[-16:],
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
