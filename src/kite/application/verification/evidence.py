"""Evidence-based verification records."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from kite.application.tools.contracts import ToolResult

EvidenceStatus = Literal["passed", "failed", "partial", "unverified"]


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    run_id: str
    tool_call_id: str
    command: str
    normalized_command: str
    cwd: str
    exit_code: int
    duration: float
    stdout_digest: str
    stderr_digest: str
    scope: str
    status: EvidenceStatus


_TEST_HINTS = (
    "pytest",
    "python -m pytest",
    "npm test",
    "go test",
    "cargo test",
    "ruff check",
    "mypy",
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _normalize_command(cmd: str) -> str:
    return re.sub(r"\s+", " ", cmd.strip().lower())


def is_check_command(command: str) -> bool:
    norm = _normalize_command(command)
    return any(h in norm for h in _TEST_HINTS)


@dataclass
class EvidenceVerifier:
    """Derive verification only from tool results — not model claims."""

    run_id: str
    records: list[EvidenceRecord] = field(default_factory=list)
    changed_hashes: dict[str, str] = field(default_factory=dict)

    def consume(self, result: ToolResult, *, command: str = "", cwd: str = "") -> EvidenceRecord | None:
        cmd = command or str(result.metadata.get("command", ""))
        if not cmd and result.output:
            cmd = result.output.split("\n", 1)[0][:200]
        if not cmd or not is_check_command(cmd):
            return None
        norm = _normalize_command(cmd)
        exit_code = int(result.metadata.get("exit_code", 0 if result.ok else 1))
        status: EvidenceStatus = "passed" if result.ok and exit_code == 0 else "failed"
        record = EvidenceRecord(
            evidence_id=str(uuid.uuid4()),
            run_id=self.run_id,
            tool_call_id=result.call_id,
            command=cmd,
            normalized_command=norm,
            cwd=cwd,
            exit_code=exit_code,
            duration=result.duration,
            stdout_digest=_digest(result.output),
            stderr_digest=_digest(result.error),
            scope="test",
            status=status,
        )
        self.records.append(record)
        return record

    def record_file_hash(self, path: str, content: bytes) -> None:
        self.changed_hashes[path] = hashlib.sha256(content).hexdigest()

    def verification_status(self) -> dict[str, Any]:
        passed = [r for r in self.records if r.status == "passed"]
        failed = [r for r in self.records if r.status == "failed"]
        if passed and not failed:
            status = "verified"
        elif passed and failed:
            status = "partial"
        elif failed:
            status = "failed"
        else:
            status = "unverified"
        return {
            "status": status,
            "evidence_count": len(self.records),
            "passed": len(passed),
            "failed": len(failed),
            "records": [asdict(r) for r in self.records],
            "changed_hashes": self.changed_hashes,
        }

    def model_claim_satisfies(self, claim: str) -> bool:
        """Model-written claims cannot satisfy verification without evidence."""
        if not self.records:
            return False
        if "test" in claim.lower() and "pass" in claim.lower():
            return any(r.status == "passed" for r in self.records)
        return False
