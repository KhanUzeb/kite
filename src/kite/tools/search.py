"""Token-efficient workspace search — grep, glob, ls."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

_SKIP_PARTS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"})


def _safe_int(value: Any, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < minimum:
        return minimum
    if maximum is not None and n > maximum:
        return maximum
    return n


def _skip_path(path: Path) -> bool:
    return any(part in _SKIP_PARTS for part in path.parts)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _format_grouped_hits(rows: list[tuple[str, int, str]], *, max_files: int) -> tuple[str, int, int]:
    """Group path:line:col lines into compact file sections."""
    by_file: dict[str, list[tuple[int, str]]] = {}
    for file_path, line_no, text in rows:
        by_file.setdefault(file_path, []).append((line_no, text))

    files = list(by_file.items())
    total_files = len(files)
    truncated_files = total_files > max_files
    shown_files = files[:max_files]

    blocks: list[str] = []
    for file_path, lines in shown_files:
        blocks.append(f"{file_path} ({len(lines)} hit{'s' if len(lines) != 1 else ''})")
        for line_no, text in lines:
            blocks.append(f"  {line_no}: {text}")
        blocks.append("")

    body = "\n".join(blocks).rstrip()
    if truncated_files:
        body += f"\n… +{total_files - max_files} more files (use files_only=true or narrower path/glob) …"
    return body, len(rows), total_files


def _parse_rg_line(raw: str, root: Path) -> tuple[str, int, str] | None:
    """Parse `path:line:content` or `path:line:col:content`."""
    if not raw.strip():
        return None
    parts = raw.split(":", 2)
    if len(parts) < 3:
        return None
    file_path, line_s, text = parts[0], parts[1], parts[2]
    try:
        line_no = int(line_s)
    except ValueError:
        # path:line:col:content — re-split from the right
        bits = raw.split(":")
        if len(bits) < 4:
            return None
        file_path = ":".join(bits[:-3]) if len(bits) > 3 else bits[0]
        try:
            line_no = int(bits[-3])
            text = ":".join(bits[-2:])
        except ValueError:
            return None
    rel = file_path
    try:
        rel = _rel(Path(file_path).resolve(), root.resolve())
    except OSError:
        rel = file_path
    return rel, line_no, text.rstrip()


def grep_search(
    *,
    pattern: str,
    root: Path,
    cwd: str,
    glob_pat: str = "",
    max_hits: int = 40,
    max_files: int = 30,
    ignore_case: bool = False,
    fixed: bool = False,
    files_only: bool = False,
    count_only: bool = False,
    context: int = 0,
    child_env: Callable[[str], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Search file contents — ripgrep when available, Python fallback otherwise."""
    max_hits = _safe_int(max_hits, 40, minimum=1, maximum=500)
    max_files = _safe_int(max_files, 30, minimum=1, maximum=200)
    context = _safe_int(context, 0, minimum=0, maximum=5)
    env = child_env(cwd) if child_env else None

    rg = shutil.which("rg")
    if rg:
        cmd = [
            rg,
            "--color",
            "never",
            "--no-heading",
            "-g",
            "!.git",
            "-g",
            "!node_modules",
            "-g",
            "!.venv",
            "-g",
            "!__pycache__",
        ]
        if files_only:
            cmd.append("--files-with-matches")
        elif count_only:
            cmd.append("--count")
        else:
            cmd.append("--line-number")
            if context > 0:
                cmd.extend(["-C", str(context)])
        if ignore_case:
            cmd.append("-i")
        if fixed:
            cmd.append("-F")
        if glob_pat:
            cmd.extend(["--glob", glob_pat])
        if not files_only and not count_only:
            cmd.extend(["--max-count", str(max_hits)])
        cmd.extend(["-e", pattern, str(root)])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=25,
                cwd=cwd,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": str(e), "output": str(e)}
        lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        if files_only:
            rels = []
            for ln in lines[:max_files]:
                try:
                    rels.append(_rel(Path(ln).resolve(), root.resolve()))
                except OSError:
                    rels.append(ln)
            body = "\n".join(rels) if rels else "(no matches)"
            extra = max(0, len(lines) - len(rels))
            summary = f"{len(lines)} file(s) matched"
            if extra:
                body += f"\n… +{extra} more files (raise max_files) …"
                summary += f", showing {len(rels)}"
            return {
                "ok": True,
                "output": body,
                "hits": len(lines),
                "files": len(lines),
                "engine": "rg",
                "summary": summary,
            }
        if count_only:
            body = "\n".join(lines[:max_files]) if lines else "(no matches)"
            total = sum(int(ln.split(":", 1)[-1]) for ln in lines if ":" in ln) if lines else 0
            return {
                "ok": True,
                "output": body,
                "hits": total,
                "files": len(lines),
                "engine": "rg",
                "summary": f"{len(lines)} file(s), {total} match(es)",
            }

        parsed: list[tuple[str, int, str]] = []
        for ln in lines:
            row = _parse_rg_line(ln, root)
            if row:
                parsed.append(row)
        if context > 0:
            body = "\n".join(lines[: max_hits * (1 + context * 2)]) or "(no matches)"
            truncated = len(lines) > max_hits
            if truncated:
                body += "\n… truncated …"
            return {
                "ok": True,
                "output": body,
                "hits": len(parsed),
                "engine": "rg",
                "summary": f"{len(parsed)} line hit(s)",
            }

        body, hit_count, file_count = _format_grouped_hits(parsed, max_files=max_files)
        if not body:
            body = "(no matches)"
        truncated = hit_count >= max_hits
        if truncated:
            body += "\n… hit limit reached (raise max_hits or narrow search) …"
        return {
            "ok": True,
            "output": body,
            "hits": hit_count,
            "files": file_count,
            "engine": "rg",
            "summary": f"{hit_count} hit(s) in {file_count} file(s)",
        }

    # Python fallback
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        return {"ok": False, "error": f"invalid regex: {e}", "output": f"invalid regex: {e}"}
    if fixed:
        needle = pattern

    def _match(line: str) -> bool:
        if fixed:
            return needle in line if not ignore_case else needle.lower() in line.lower()
        return rx.search(line) is not None

    hits: list[tuple[str, int, str]] = []
    file_hits: dict[str, int] = {}
    if root.is_file():
        paths = [root]
    elif glob_pat:
        glob_use = glob_pat
        paths = sorted(root.rglob(glob_use) if "**" in glob_use else root.glob(glob_use))
    else:
        paths = sorted(p for p in root.rglob("*") if p.is_file() and not _skip_path(p))
    for p in paths:
        if not p.is_file() or _skip_path(p):
            continue
        rel = _rel(p, root if root.is_dir() else p.parent)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        local = 0
        for i, line in enumerate(text.splitlines(), 1):
            if _match(line):
                local += 1
                if files_only:
                    file_hits[rel] = file_hits.get(rel, 0) + 1
                    break
                if count_only:
                    file_hits[rel] = file_hits.get(rel, 0) + 1
                    continue
                hits.append((rel, i, line[:240]))
                if len(hits) >= max_hits:
                    break
        if not files_only and not count_only and len(hits) >= max_hits:
            break
        if files_only and len(file_hits) >= max_files:
            break

    if files_only:
        rels = list(file_hits.keys())[:max_files]
        body = "\n".join(rels) if rels else "(no matches)"
        return {
            "ok": True,
            "output": body,
            "hits": sum(file_hits.values()),
            "files": len(file_hits),
            "engine": "python",
            "summary": f"{len(file_hits)} file(s) matched",
        }
    if count_only:
        lines = [f"{k}:{v}" for k, v in list(file_hits.items())[:max_files]]
        body = "\n".join(lines) if lines else "(no matches)"
        total = sum(file_hits.values())
        return {
            "ok": True,
            "output": body,
            "hits": total,
            "files": len(file_hits),
            "engine": "python",
            "summary": f"{len(file_hits)} file(s), {total} match(es)",
        }

    body, hit_count, file_count = _format_grouped_hits(hits, max_files=max_files)
    if not body:
        body = "(no matches)"
    return {
        "ok": True,
        "output": body,
        "hits": hit_count,
        "files": file_count,
        "engine": "python",
        "summary": f"{hit_count} hit(s) in {file_count} file(s)",
    }


def glob_search(
    *,
    pattern: str,
    root: Path,
    max_matches: int = 120,
    files_only: bool = True,
    dirs_only: bool = False,
    sort: str = "name",
) -> dict[str, Any]:
    """Match paths under root — recursive when pattern contains ``**``."""
    max_matches = _safe_int(max_matches, 120, minimum=1, maximum=2000)
    if "**" in pattern:
        candidates = root.rglob(pattern.removeprefix("**/").lstrip("/"))
    else:
        candidates = root.glob(pattern)

    matches: list[Path] = []
    for p in candidates:
        if _skip_path(p):
            continue
        if dirs_only and not p.is_dir():
            continue
        if files_only and not p.is_file():
            continue
        matches.append(p)

    if sort == "mtime":
        matches.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    else:
        matches.sort(key=lambda p: str(p).lower())

    total = len(matches)
    truncated = total > max_matches
    shown = matches[:max_matches]
    rels = [_rel(p, root) for p in shown]
    body = "\n".join(rels) if rels else "(no matches)"
    if truncated:
        body += f"\n… +{total - max_matches} more (raise max or narrow pattern) …"
    return {
        "ok": True,
        "output": body,
        "count": total,
        "shown": len(shown),
        "summary": f"{total} match(es)" + (f", showing {len(shown)}" if truncated else ""),
    }


def ls_search(
    *,
    path: Path,
    glob_pat: str = "",
    max_entries: int = 200,
) -> dict[str, Any]:
    """List one directory level — optional glob filter."""
    max_entries = _safe_int(max_entries, 200, minimum=1, maximum=1000)
    if not path.exists():
        return {"ok": False, "error": f"not found: {path}", "output": f"not found: {path}"}
    if path.is_file():
        return {"ok": True, "output": path.name, "count": 1, "summary": "1 file"}

    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        return {"ok": False, "error": str(e), "output": str(e)}

    lines: list[str] = []
    for e in entries:
        if e.name in _SKIP_PARTS:
            continue
        if glob_pat and not e.match(glob_pat):
            continue
        suffix = "/" if e.is_dir() else ""
        lines.append(e.name + suffix)
        if len(lines) >= max_entries:
            break

    body = "\n".join(lines) if lines else "(empty)"
    truncated = len(entries) > len(lines)
    if truncated:
        body += f"\n… +{len(entries) - len(lines)} more entries …"
    return {
        "ok": True,
        "output": body,
        "count": len(lines),
        "summary": f"{len(lines)} entr{'y' if len(lines) == 1 else 'ies'}",
    }


__all__ = ["glob_search", "grep_search", "ls_search"]
