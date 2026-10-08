"""Token-efficient workspace search — grep, glob, ls."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from kite.env.shell import iter_bounded_lines
from kite.guardrails.redact import redact_string
from kite.guardrails.sandbox import is_protected
from kite.util import bounded_int

_SKIP_PARTS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"})
_GREP_MAX_FILE_BYTES = 1_000_000
_RG_DENY_GLOBS = ("!.env", "!.env.*", "!*.env")
_RG_LINE = re.compile(r"^(\d+)([:-])(.*)$")


def _skip_path(path: Path) -> bool:
    return any(part in _SKIP_PARTS for part in path.parts)


def _sensitive_file(path: Path) -> bool:
    from kite.guardrails.sandbox import is_sensitive_basename

    return is_sensitive_basename(path.name)


def _is_file_safe(path: Path) -> bool:
    """is_file() that never raises — unreadable entries are simply not files."""
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir_safe(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _mtime_safe(path: Path) -> float:
    """st_mtime for sort keys — missing/unreadable files sort first, never crash."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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


def _search_paths(root: Path, glob_pat: str) -> Iterator[Path]:
    if _is_file_safe(root):
        yield root
        return
    for directory, dirs, files in os.walk(root):
        # Prune before descending, rather than walking caches only to discard
        # every file afterwards. Never follow directory symlinks.
        dirs[:] = sorted(name for name in dirs if name not in _SKIP_PARTS)
        for name in sorted(files):
            path = Path(directory) / name
            if not glob_pat or path.relative_to(root).match(glob_pat):
                yield path


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
    max_hits = bounded_int(max_hits, 40, minimum=1, maximum=500)
    max_files = bounded_int(max_files, 30, minimum=1, maximum=200)
    context = bounded_int(context, 0, minimum=0, maximum=5)
    if _sensitive_file(root) or (root.is_symlink() and is_protected(root)):
        return {"ok": True, "output": "(no matches)", "hits": 0, "files": 0,
                "summary": "0 hit(s) in 0 file(s)"}

    rg = shutil.which("rg")
    if rg:
        env = child_env(cwd) if child_env else None
        cmd = [
            rg, "--color", "never", "--no-heading", "--with-filename",
            "--max-filesize", str(_GREP_MAX_FILE_BYTES),
        ]
        if files_only:
            cmd.append("--files-with-matches")
        elif count_only:
            cmd.extend(["--count", "--null"])
        else:
            cmd.extend(["--line-number", "--null", "--max-count", str(max_hits)])
            if context:
                cmd.extend(["-C", str(context)])
        if ignore_case:
            cmd.append("-i")
        if fixed:
            cmd.append("-F")
        if glob_pat:
            cmd.extend(["--glob", glob_pat])
        for glob in (*_RG_DENY_GLOBS, *("!" + part for part in _SKIP_PARTS)):
            cmd.extend(["-g", glob])
        cmd.extend(["-e", pattern, str(root)])
        lines: list[str] = []
        parsed: list[tuple[str, int, str]] = []
        total_hits = total_files = 0
        timed_out = threading.Event()
        limited = False
        after_limit = 0
        limit_path = ""
        relative_root = root if root.is_dir() else root.parent
        try:
            with tempfile.TemporaryFile() as errors:
                with subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=errors, text=True,
                    encoding="utf-8", errors="replace", cwd=cwd, env=env,
                ) as proc:
                    def expire() -> None:
                        timed_out.set()
                        proc.kill()

                    timer = threading.Timer(25, expire)
                    timer.daemon = True
                    timer.start()
                    try:
                        assert proc.stdout is not None
                        for raw in iter_bounded_lines(proc.stdout, max_chars=_GREP_MAX_FILE_BYTES + 4096):
                            raw = raw.rstrip("\n")
                            if not raw or raw == "--":
                                if context and raw and not after_limit:
                                    lines.append(raw)
                                continue
                            path_text, _, content = raw.partition("\0") if not files_only else (raw, "", "")
                            path = Path(path_text)
                            if after_limit and path_text != limit_path:
                                proc.terminate()
                                break
                            if _sensitive_file(path):
                                continue
                            rel = _rel(path, relative_root)
                            if files_only:
                                total_files += 1
                                if len(lines) < max_files:
                                    lines.append(rel)
                                continue
                            if count_only:
                                total_files += 1
                                total_hits += int(content)
                                if len(lines) < max_files:
                                    lines.append(f"{path_text}:{content}")
                                continue
                            match = _RG_LINE.match(content)
                            if match is None:
                                continue
                            number, separator, text = match.groups()
                            text = redact_string(text)
                            if separator == ":" and total_hits < max_hits:
                                total_hits += 1
                                parsed.append((rel, int(number), text[:240].rstrip()))
                            if context:
                                lines.append(f"{path_text}{separator}{number}{separator}{text[:240]}")
                            if total_hits >= max_hits:
                                limited = True
                                limit_path = path_text
                                after_limit += 1
                                if after_limit > context:
                                    proc.terminate()
                                    break
                    finally:
                        timer.cancel()
                    rc = proc.wait()
                if timed_out.is_set():
                    err = "ripgrep timed out after 25s"
                    return {"ok": False, "error": err, "output": err}
                if rc not in (0, 1) and not limited:
                    errors.seek(0)
                    err = errors.read(16_000).decode("utf-8", errors="replace").strip() or f"ripgrep exited {rc}"
                    return {"ok": False, "error": err, "output": err}
        except OSError as e:
            return {"ok": False, "error": str(e), "output": str(e)}
        if files_only:
            body = "\n".join(lines) or "(no matches)"
            summary = f"{total_files} file(s) matched"
            if total_files > len(lines):
                body += f"\n… +{total_files - len(lines)} more files (raise max_files) …"
                summary += f", showing {len(lines)}"
            return {"ok": True, "output": body, "hits": total_files, "files": total_files,
                    "engine": "rg", "summary": summary}
        if count_only:
            return {"ok": True, "output": "\n".join(lines) or "(no matches)", "hits": total_hits,
                    "files": total_files, "engine": "rg", "summary": f"{total_files} file(s), {total_hits} match(es)"}
        if context:
            body = "\n".join(lines) or "(no matches)"
            if limited:
                body += "\n… truncated …"
            return {"ok": True, "output": body, "hits": total_hits, "engine": "rg",
                    "summary": f"{total_hits} line hit(s)"}
        body, hit_count, file_count = _format_grouped_hits(parsed, max_files=max_files)
        body = body or "(no matches)"
        if limited:
            body += "\n… hit limit reached (raise max_hits or narrow search) …"
        return {"ok": True, "output": body, "hits": hit_count, "files": file_count,
                "engine": "rg", "summary": f"{hit_count} hit(s) in {file_count} file(s)"}

    # Python fallback
    needle = pattern.lower() if ignore_case else pattern
    rx = None
    if not fixed:
        try:
            rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            return {"ok": False, "error": f"invalid regex: {e}", "output": f"invalid regex: {e}"}

    def _match(line: str) -> bool:
        if fixed:
            return needle in (line.lower() if ignore_case else line)
        return rx.search(line) is not None if rx is not None else False

    hits: list[tuple[str, int, str]] = []
    context_lines: list[str] = []
    total_hits = total_files = 0
    file_hits: dict[str, int] = {}
    relative_root = root if _is_dir_safe(root) else root.parent
    for p in _search_paths(root, glob_pat):
        if not _is_file_safe(p) or _skip_path(p) or _sensitive_file(p):
            continue
        rel = _rel(p, relative_root)
        try:
            if p.stat().st_size > _GREP_MAX_FILE_BYTES:
                continue
            if p.is_symlink() and is_protected(p):
                continue
            with p.open("r", encoding="utf-8", errors="replace") as handle:
                text = handle.read(_GREP_MAX_FILE_BYTES + 1)
            if len(text) > _GREP_MAX_FILE_BYTES or "\0" in text:
                continue
        except OSError:
            continue
        source_lines = text.splitlines()
        local_hits = 0
        shown_until = 0
        for i, line in enumerate(source_lines, 1):
            if not _match(line):
                continue
            local_hits += 1
            if files_only:
                break
            if count_only:
                continue
            hits.append((rel, i, redact_string(line)[:240]))
            if context:
                start = max(shown_until, i - 1 - context)
                end = min(len(source_lines), i + context)
                if context_lines and start > shown_until:
                    context_lines.append("--")
                for index in range(start, end):
                    separator = ":" if _match(source_lines[index]) else "-"
                    safe = redact_string(source_lines[index])[:240]
                    context_lines.append(f"{p}{separator}{index + 1}{separator}{safe}")
                shown_until = end
            if len(hits) >= max_hits:
                break
        if local_hits:
            total_files += 1
            total_hits += local_hits
            if len(file_hits) < max_files:
                file_hits[rel] = local_hits
        if not files_only and not count_only and len(hits) >= max_hits:
            break

    if files_only:
        body = "\n".join(file_hits) or "(no matches)"
        summary = f"{total_files} file(s) matched"
        if total_files > len(file_hits):
            body += f"\n… +{total_files - len(file_hits)} more files (raise max_files) …"
            summary += f", showing {len(file_hits)}"
        return {
            "ok": True,
            "output": body,
            "hits": total_files,
            "files": total_files,
            "engine": "python",
            "summary": summary,
        }
    if count_only:
        lines = [f"{k}:{v}" for k, v in list(file_hits.items())[:max_files]]
        body = "\n".join(lines) if lines else "(no matches)"
        return {
            "ok": True,
            "output": body,
            "hits": total_hits,
            "files": total_files,
            "engine": "python",
            "summary": f"{total_files} file(s), {total_hits} match(es)",
        }

    if context:
        body = "\n".join(context_lines) or "(no matches)"
        if len(hits) >= max_hits:
            body += "\n… truncated …"
        return {"ok": True, "output": body, "hits": len(hits), "engine": "python",
                "summary": f"{len(hits)} line hit(s)"}

    body, hit_count, file_count = _format_grouped_hits(hits, max_files=max_files)
    if not body:
        body = "(no matches)"
    if hit_count >= max_hits:
        body += "\n… hit limit reached (raise max_hits or narrow search) …"
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
    max_matches = bounded_int(max_matches, 120, minimum=1, maximum=2000)
    if "**" in pattern:
        candidates = root.rglob(pattern.removeprefix("**/").lstrip("/"))
    else:
        candidates = root.glob(pattern)

    matches: list[Path] = []
    for p in candidates:
        if _skip_path(p):
            continue
        # is_file()/is_dir() re-raise permission errors — skip those entries.
        if dirs_only and not _is_dir_safe(p):
            continue
        if files_only and not _is_file_safe(p):
            continue
        matches.append(p)

    if sort == "mtime":
        matches.sort(key=_mtime_safe, reverse=True)
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
    max_entries = bounded_int(max_entries, 200, minimum=1, maximum=1000)
    if not path.exists():
        return {"ok": False, "error": f"not found: {path}", "output": f"not found: {path}"}
    if _is_file_safe(path):
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
