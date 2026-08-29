"""Git checkpoints — one kite commit per task/todo, not per file edit."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


KITE_MARK = "kite:"


def _run(cwd: str | Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )


def git_branch(cwd: str | Path) -> str:
    proc = _run(cwd, "git", "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def is_repo(cwd: str | Path) -> bool:
    proc = _run(cwd, "git", "rev-parse", "--is-inside-work-tree")
    return proc.returncode == 0 and (proc.stdout or "").strip() == "true"


def _short_task(text: str, limit: int = 72) -> str:
    line = " ".join((text or "").strip().split())
    if len(line) <= limit:
        return line or "agent edits"
    return line[: limit - 1] + "…"


@dataclass
class GitCheckpoints:
    cwd: Path
    shas: list[str] = field(default_factory=list)
    _pending: list[str] = field(default_factory=list)
    _pending_set: set[str] = field(default_factory=set)
    _bucket: str = ""

    @classmethod
    def open(cls, cwd: str | Path) -> GitCheckpoints:
        return cls(cwd=Path(cwd))

    def record(self, path: str, task: str) -> dict | None:
        """Stage a path under `task`. If the task changed, commit the previous bucket first."""
        label = _short_task(task)
        flushed = None
        if self._pending and self._bucket and self._bucket != label:
            flushed = self.flush()
        self._bucket = label
        resolved = str(path)
        if resolved not in self._pending_set:
            self._pending_set.add(resolved)
            self._pending.append(resolved)
        return flushed

    def flush(self, message: str | None = None) -> dict | None:
        """Commit all paths recorded for the current task. No-op if nothing pending."""
        if not self._pending:
            self._bucket = ""
            return None
        files = list(self._pending)
        subject = _short_task(message or self._bucket or "agent edits")
        sha = self._commit_paths(files, subject)
        self._pending = []
        self._pending_set.clear()
        self._bucket = ""
        if not sha:
            return None
        return {"sha": sha, "message": f"{KITE_MARK} {subject}", "files": files}

    def flush_if_task_changed(self, new_task: str, *, has_in_progress: bool) -> dict | None:
        """Commit the open bucket when the checklist leaves that task."""
        if not self._pending:
            return None
        label = _short_task(new_task)
        if has_in_progress and self._bucket and label == self._bucket:
            return None
        return self.flush()

    def _commit_paths(self, paths: list[str], subject: str) -> str | None:
        if not is_repo(self.cwd) or not paths:
            return None
        add = _run(self.cwd, "git", "add", "--", *paths)
        if add.returncode != 0:
            return None
        body_files = "\n".join(paths[:20])
        extra = f"\n\n{len(paths) - 20} more files" if len(paths) > 20 else ""
        msg = f"{KITE_MARK} {subject}\n\n{body_files}{extra}"
        proc = _run(self.cwd, "git", "commit", "-m", msg, "--no-verify")
        if proc.returncode != 0:
            return None
        sha = _run(self.cwd, "git", "rev-parse", "HEAD")
        if sha.returncode != 0:
            return None
        digest = sha.stdout.strip()
        self.shas.append(digest)
        return digest

    def commit(self, paths: list[str], message: str) -> str | None:
        """Immediate commit (tests / explicit). Prefer record()+flush() for task grouping."""
        for p in paths:
            self.record(p, message)
        result = self.flush(message=message)
        return None if result is None else str(result["sha"])

    def undo(self) -> tuple[bool, str]:
        """Revert the last kite commit. Refuses if HEAD is not ours."""
        if not is_repo(self.cwd):
            return False, "not a git repo — nothing to undo"
        log = _run(self.cwd, "git", "log", "-1", "--pretty=%s")
        subject = (log.stdout or "").strip()
        if not subject.startswith(KITE_MARK):
            return False, "HEAD is not a kite commit; /undo only reverts agent commits"
        reset = _run(self.cwd, "git", "reset", "--hard", "HEAD~1")
        if reset.returncode != 0:
            return False, (reset.stderr or "git reset failed").strip()
        if self.shas:
            self.shas.pop()
        return True, "reverted last kite commit"
