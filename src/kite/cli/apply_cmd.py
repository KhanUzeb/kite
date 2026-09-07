"""Apply cloud/local task output back to the working tree."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from kite.tools.coding import _unified_diff


def _apply_edit(path: Path, old: str, new: str, *, replace_all: bool = False) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if old not in text:
        return False
    after = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    path.write_text(after, encoding="utf-8")
    return True


def _apply_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def extract_patches_from_trajectory(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull write/edit actions from a kite trajectory."""
    patches: list[dict[str, Any]] = []
    for m in data.get("messages") or []:
        extra = m.get("extra") or {}
        for action in extra.get("actions") or []:
            tool = action.get("tool")
            args = action.get("arguments") or {}
            if tool == "write":
                patches.append({"tool": "write", "path": args.get("path"), "content": args.get("content")})
            elif tool == "edit":
                patches.append(
                    {
                        "tool": "edit",
                        "path": args.get("path"),
                        "old": args.get("old"),
                        "new": args.get("new"),
                        "replace_all": args.get("replace_all"),
                    }
                )
    return patches


def _path_inside_workspace(target: Path, root: Path) -> bool:
    root_res = root.expanduser().resolve()
    try:
        resolved = target.expanduser().resolve()
    except OSError:
        return False
    root_s, res_s = str(root_res), str(resolved)
    if res_s == root_s:
        return True
    if not res_s.startswith(root_s):
        return False
    if len(res_s) > len(root_s) and res_s[len(root_s)] not in "\\/":
        return False
    return True


def apply_trajectory(path: Path, *, cwd: str, dry_run: bool = False) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    patches = extract_patches_from_trajectory(data)
    root = Path(cwd).resolve()
    applied: list[str] = []
    skipped: list[str] = []
    for p in patches:
        rel = p.get("path")
        if not rel:
            skipped.append("missing path")
            continue
        target = (root / str(rel)).resolve()
        if not _path_inside_workspace(target, root):
            skipped.append(f"escapes workspace: {rel}")
            continue
        if dry_run:
            applied.append(f"would {p['tool']} {rel}")
            continue
        if p["tool"] == "write":
            _apply_write(target, str(p.get("content") or ""))
            applied.append(f"write {rel}")
        elif p["tool"] == "edit":
            ok = _apply_edit(
                target,
                str(p.get("old") or ""),
                str(p.get("new") or ""),
                replace_all=bool(p.get("replace_all")),
            )
            if ok:
                applied.append(f"edit {rel}")
            else:
                skipped.append(f"edit failed: {rel}")
    return {"applied": applied, "skipped": skipped, "count": len(applied)}


def apply_unified_diff(diff_text: str, *, cwd: str, dry_run: bool = False) -> dict[str, Any]:
    """Apply simple unified diffs (single-file heuristic)."""
    root = Path(cwd).resolve()
    applied: list[str] = []
    skipped: list[str] = []

    def _flush_file() -> None:
        nonlocal current_path, old_lines, new_lines
        if not current_path:
            return
        target = (root / current_path).resolve()
        if not _path_inside_workspace(target, root):
            skipped.append(f"escapes workspace: {current_path}")
        elif not dry_run and target.is_file():
            before = target.read_text(encoding="utf-8", errors="replace")
            after = "\n".join(new_lines)
            if not after.endswith("\n") and before.endswith("\n"):
                after += "\n"
            target.write_text(after, encoding="utf-8")
            applied.append(current_path)
        elif dry_run:
            applied.append(f"would patch {current_path}")
        current_path = None
        old_lines = []
        new_lines = []

    current_path: str | None = None
    old_lines: list[str] = []
    new_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            _flush_file()
            current_path = line[6:].strip()
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            continue
        elif current_path:
            if line.startswith("-") and not line.startswith("---"):
                old_lines.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                new_lines.append(line[1:])
            elif line.startswith(" "):
                old_lines.append(line[1:])
                new_lines.append(line[1:])
    _flush_file()
    return {"applied": applied, "skipped": skipped, "count": len(applied)}
