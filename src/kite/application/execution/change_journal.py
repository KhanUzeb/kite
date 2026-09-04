"""Agent-owned file change journal — safe undo without git reset --hard."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileSnapshot:
    path: str
    existed: bool
    content: bytes | None
    mode: int | None
    hash: str


@dataclass
class ChangeRecord:
    path: str
    preimage: FileSnapshot
    postimage_hash: str
    agent_owned: bool = True


@dataclass
class RestoreConflict:
    path: str
    reason: str
    current_hash: str
    expected_hash: str


@dataclass
class ChangeJournal:
    """Track agent mutations for conflict-aware restore."""

    workspace: Path
    records: list[ChangeRecord] = field(default_factory=list)

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _snapshot(self, path: Path) -> FileSnapshot:
        rel = str(path.relative_to(self.workspace)) if path.is_relative_to(self.workspace) else str(path)
        if not path.exists():
            return FileSnapshot(path=rel, existed=False, content=None, mode=None, hash="")
        data = path.read_bytes()
        return FileSnapshot(
            path=rel,
            existed=True,
            content=data,
            mode=path.stat().st_mode,
            hash=self._hash(data),
        )

    def record_write(self, path: str | Path, *, agent_owned: bool = True) -> None:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve()
        snap = self._snapshot(p)
        self.records.append(
            ChangeRecord(path=snap.path, preimage=snap, postimage_hash="", agent_owned=agent_owned),
        )

    def record_after_write(self, path: str | Path) -> None:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        post = self._snapshot(p.resolve())
        for rec in reversed(self.records):
            if rec.path == post.path and not rec.postimage_hash:
                rec.postimage_hash = post.hash
                return
        self.record_write(p)
        self.records[-1].postimage_hash = post.hash

    def restore(self) -> tuple[list[str], list[RestoreConflict]]:
        """Restore only unchanged agent-owned files; report conflicts."""
        restored: list[str] = []
        conflicts: list[RestoreConflict] = []
        for rec in reversed(self.records):
            if not rec.agent_owned:
                continue
            target = self.workspace / rec.path
            current = self._snapshot(target) if target.exists() else FileSnapshot(
                path=rec.path, existed=False, content=None, mode=None, hash="",
            )
            if rec.postimage_hash and current.hash and current.hash != rec.postimage_hash:
                conflicts.append(
                    RestoreConflict(
                        path=rec.path,
                        reason="user modified after agent write",
                        current_hash=current.hash,
                        expected_hash=rec.postimage_hash,
                    ),
                )
                continue
            pre = rec.preimage
            if pre.existed:
                if pre.content is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(pre.content)
                    restored.append(rec.path)
            elif target.exists():
                target.unlink()
                restored.append(rec.path)
        return restored, conflicts
