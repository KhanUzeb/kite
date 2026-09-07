"""Built-in tools: read / write / edit / bash / grep / glob / ls / skill / todo / task / webfetch / websearch / webcrawl / memory."""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from kite.env.venv import prepare_child_env
from kite.guardrails import GuardrailPolicy, redact_secrets
from kite.memory.store import MemoryScope, MemoryStore
from kite.skills.loader import Skill, format_skill_invocation
from kite.tools import Tool
from kite.tools.store import TodoStore
from kite.tools.web import webcrawl, websearch
from kite.tools.web import webfetch as fetch_url

try:
    from kite.context.workspace import ExecutionSession
except ImportError:  # pragma: no cover
    ExecutionSession = None  # type: ignore[misc, assignment]

try:
    from kite.agent.cancel import CancelToken
    from kite.agent.events import Event
except ImportError:  # pragma: no cover
    CancelToken = None  # type: ignore[misc, assignment]
    Event = None  # type: ignore[misc, assignment]


_SKIP_NAMES = frozenset({".git", ".venv", "node_modules", "__pycache__"})
_BASH_MAX_OUTPUT_BYTES = 256_000
_STDIN_MAX_BYTES = 2_000_000


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


def _resolve(path: str, cwd: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(cwd) / p
    return p.resolve()


def _io_fail(path: Path, exc: BaseException) -> dict[str, Any]:
    msg = f"{type(exc).__name__}: {exc}"
    return {"ok": False, "error": msg, "path": str(path), "output": msg}


def _todo_view(items: list[Any]) -> dict[str, Any]:
    lines = [f"{x['status']:12} {x['content']}" for x in items]
    return {"ok": True, "output": "\n".join(lines) or "(empty plan)", "items": items}


def _list_dir_names(path: Path) -> tuple[list[str], str | None]:
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        return [], str(e)
    names = []
    for e in entries:
        if e.name in _SKIP_NAMES:
            continue
        names.append(e.name + ("/" if e.is_dir() else ""))
    return names, None


def _unified_diff(path: str, before: str, after: str) -> str:
    rel = path.replace("\\", "/")
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )
    return ("\n".join(lines) + "\n") if lines else ""


def _line_trimmed_unique_match(text: str, old: str) -> str | None:
    """One bounded fuzzy try: match old_string ignoring trailing whitespace per line."""
    if not old.strip():
        return None
    old_lines = old.splitlines()
    text_lines = text.splitlines()
    if not old_lines or len(old_lines) > len(text_lines):
        return None
    matches: list[str] = []
    for i in range(len(text_lines) - len(old_lines) + 1):
        chunk_lines = text_lines[i : i + len(old_lines)]
        if all(a.rstrip() == b.rstrip() for a, b in zip(chunk_lines, old_lines, strict=False)):
            matched = "\n".join(chunk_lines)
            if old.endswith("\n") and matched and not matched.endswith("\n"):
                matched += "\n"
            matches.append(matched)
    if len(matches) == 1:
        return matches[0]
    return None


def make_coding_tools(
    cwd: str | None = None,
    timeout: int = 30,
    *,
    enabled: list[str] | None = None,
    guardrails: GuardrailPolicy | None = None,
    skills: list[Skill] | None = None,
    todos: TodoStore | None = None,
    memory: MemoryStore | None = None,
    orchestrator=None,
    execution: ExecutionSession | None = None,
    cancel: CancelToken | None = None,
    jobs=None,
    on_event=None,
    auto_venv: bool = True,
) -> list[Tool]:
    def _root() -> str:
        if execution is not None:
            return str(execution.execution_cwd)
        return cwd or os.getcwd()

    _root()
    project_root = str(execution.project_root) if execution is not None else (cwd or os.getcwd())

    def _child_env(workdir: str) -> dict[str, str]:
        venv = execution.venv_path if execution is not None else None
        return prepare_child_env(
            cwd=workdir,
            project_root=project_root,
            venv=venv,
            auto_venv=auto_venv,
        )

    def _emit_bash_line(line: str) -> None:
        if on_event is None or Event is None:
            return
        on_event(Event(kind="tool_output", payload={"line": line, "tool": "bash"}))
    allow = set(
        enabled
        or [
            "read",
            "write",
            "edit",
            "bash",
            "grep",
            "glob",
            "ls",
            "set_cwd",
            "skill",
            "todo_write",
            "todo_read",
            "task",
            "webfetch",
            "websearch",
            "webcrawl",
            "subagent",
            "memory",
            "submit",
        ]
    )
    skill_by_name = {s.name: s for s in (skills or [])}
    store = todos or TodoStore()
    mem = memory or MemoryStore.open(project_root)

    def gated(tool_name: str, arguments: dict[str, Any], fn):
        if guardrails is not None:
            verdict = guardrails.check_tool_call(tool_name, arguments)
            if not verdict.allowed:
                return {"ok": False, "error": verdict.reason, "output": verdict.reason, "blocked": True}
            if verdict.rewritten_args is not None:
                arguments = verdict.rewritten_args
        result = fn(arguments)
        if guardrails is not None:
            result = guardrails.clamp_output(tool_name, result)
        return result

    def read_file(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve(str(args["path"]), _root())
        if not path.exists():
            msg = f"not found: {path}"
            return {"ok": False, "error": msg, "path": str(path), "output": msg}
        if path.is_dir():
            # Windows open() on a directory raises PermissionError (errno 13),
            # not IsADirectoryError — list it instead of crashing the run.
            names, err = _list_dir_names(path)
            if err:
                msg = f"{path} is a directory ({err}). Use ls."
                return {"ok": False, "error": msg, "path": str(path), "output": msg}
            listing = "\n".join(names) if names else "(empty)"
            msg = f"{path} is a directory. Use ls, or read a file inside it.\n{listing}"
            return {"ok": True, "path": str(path), "output": msg, "directory": True, "count": len(names)}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return _io_fail(path, e)
        start = _safe_int(args.get("offset"), 1, minimum=1)
        limit_raw = args.get("limit")
        limit = _safe_int(limit_raw, 0, minimum=0) if limit_raw is not None else None
        numbered = bool(args.get("numbered"))
        lines = text.splitlines(keepends=True)
        chunk = lines[start - 1 :] if start > 1 else lines
        if limit is not None and limit > 0:
            chunk = chunk[:limit]
        if numbered:
            body = "".join(f"{i + start:6}|{line}" for i, line in enumerate(chunk))
        else:
            body = "".join(chunk)
        truncated = False
        if limit is None and len(lines) > 200:
            chunk = lines[:200]
            if numbered:
                body = "".join(f"{i + start:6}|{line}" for i, line in enumerate(chunk))
            else:
                body = "".join(chunk)
            body += f"\n... [{len(lines) - 200} lines truncated; use bash: wc -l / head / sed -n, or read offset/limit] ...\n"
            truncated = True
        return {"ok": True, "path": str(path), "output": body, "truncated": truncated}

    def write_file(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve(str(args["path"]), _root())
        if guardrails is not None:
            verdict = guardrails.check_path(str(path), for_write=True)
            if not verdict.allowed:
                return {"ok": False, "error": verdict.reason, "output": verdict.reason, "blocked": True}
        if path.exists() and path.is_dir():
            msg = f"cannot write: {path} is a directory"
            return {"ok": False, "error": msg, "path": str(path), "output": msg}
        after = str(args["content"])
        try:
            before = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(after, encoding="utf-8")
        except OSError as e:
            return _io_fail(path, e)
        diff = _unified_diff(str(path), before, after)
        return {
            "ok": True,
            "path": str(path),
            "bytes": path.stat().st_size,
            "output": f"wrote {path}",
            "diff": diff,
            "changed_paths": [str(path)],
        }

    def edit_file(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve(str(args["path"]), _root())
        if guardrails is not None:
            verdict = guardrails.check_path(str(path), for_write=True)
            if not verdict.allowed:
                return {"ok": False, "error": verdict.reason, "output": verdict.reason, "blocked": True}
        if path.is_dir():
            msg = f"cannot edit: {path} is a directory"
            return {"ok": False, "error": msg, "path": str(path), "output": msg}
        old, new = str(args["old"]), str(args["new"])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return _io_fail(path, e)
        matched = old
        count = text.count(matched)
        if count == 0:
            fuzzy = _line_trimmed_unique_match(text, old)
            if fuzzy:
                matched = fuzzy
                count = 1
        if count == 0:
            return {"ok": False, "error": "old string not found", "path": str(path), "output": "old string not found"}
        if count > 1 and not args.get("replace_all"):
            msg = f"old string found {count} times; pass replace_all=true or make it unique"
            return {"ok": False, "error": msg, "path": str(path), "output": msg}
        after = text.replace(matched, new) if args.get("replace_all") else text.replace(matched, new, 1)
        try:
            path.write_text(after, encoding="utf-8")
        except OSError as e:
            return _io_fail(path, e)
        n = count if args.get("replace_all") else 1
        return {
            "ok": True,
            "path": str(path),
            "replacements": n,
            "output": f"edited {path} ({n} hunk{'s' if n != 1 else ''})",
            "diff": _unified_diff(str(path), text, after),
            "changed_paths": [str(path)],
        }

    def bash(args: dict[str, Any]) -> dict[str, Any]:
        command = str(args["command"])
        workdir = str(args.get("cwd") or _root())
        background = bool(args.get("background"))
        # Last-line sandbox: never launch a shell outside the workspace root.
        try:
            from kite.guardrails.sandbox import clamp_cwd, workspace_root

            clamped, reason = clamp_cwd(
                workdir,
                workspace_root(_root()),
                allow_outside=bool(guardrails and guardrails.config.host_access()),
            )
            if clamped is None:
                return {"ok": False, "error": reason, "output": reason, "blocked": True}
            workdir = str(clamped)
        except Exception as e:
            reason = f"cwd sandbox check failed: {e}"
            return {"ok": False, "error": reason, "output": reason, "blocked": True}
        if background:
            if jobs is None:
                return {
                    "ok": False,
                    "error": "background jobs not configured",
                    "output": "background jobs not configured",
                }
            try:
                job = jobs.spawn_bash(
                    command,
                    cwd=workdir,
                    env=_child_env(workdir),
                )
            except OSError as e:
                return {"ok": False, "returncode": -1, "output": "", "error": str(e)}
            return {
                "ok": True,
                "job_id": job.id,
                "pid": job.pid,
                "command": command,
                "output": f"background job {job.id} (pid {job.pid})",
            }
        try:
            limit = _safe_int(args.get("timeout"), timeout, minimum=1, maximum=3600)
            from kite.env.shell import resolve_shell_invocation

            argv, cmd_text = resolve_shell_invocation(command)
            popen_kw: dict[str, Any] = {
                "cwd": workdir,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "env": _child_env(workdir),
            }
            if argv is not None:
                proc = subprocess.Popen(argv, shell=False, **popen_kw)
            else:
                proc = subprocess.Popen(cmd_text, shell=True, **popen_kw)
            output_parts: list[str] = []
            output_bytes = 0
            stream_redactions = 0

            def _emit_line(raw_line: str) -> None:
                nonlocal stream_redactions, output_bytes
                if output_bytes >= _BASH_MAX_OUTPUT_BYTES:
                    return
                safe, n = redact_secrets(raw_line)
                stream_redactions += n
                output_parts.append(safe)
                output_bytes += len(safe.encode("utf-8", errors="replace"))
                if on_event is not None:
                    _emit_bash_line(safe)
                else:
                    try:
                        sys.stderr.write(safe)
                        sys.stderr.flush()
                    except OSError:
                        pass

            def _drain() -> None:
                assert proc.stdout is not None
                try:
                    for line in iter(proc.stdout.readline, ""):
                        _emit_line(line)
                except OSError:
                    pass
                finally:
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass

            reader = threading.Thread(target=_drain, daemon=True)
            reader.start()
            deadline = time.monotonic() + limit
            rc: int | None = None
            try:
                while rc is None:
                    if cancel is not None and cancel.is_set():
                        proc.kill()
                        reader.join(timeout=1.0)
                        partial = "".join(output_parts)
                        return {
                            "ok": False,
                            "returncode": -1,
                            "output": partial,
                            "error": "cancelled",
                            "cancelled": True,
                        }
                    try:
                        rc = proc.wait(timeout=0.15)
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            proc.kill()
                            reader.join(timeout=1.0)
                            partial = "".join(output_parts)
                            return {
                                "ok": False,
                                "returncode": -1,
                                "output": partial,
                                "error": f"timeout after {limit}s",
                            }
            except OSError as e:
                try:
                    proc.kill()
                except OSError:
                    pass
                reader.join(timeout=1.0)
                return {"ok": False, "returncode": -1, "output": "".join(output_parts), "error": str(e)}
            reader.join(timeout=2.0)
            output = "".join(output_parts)
            if output_bytes >= _BASH_MAX_OUTPUT_BYTES:
                output += "\n...[guardrail truncated bash output]...\n"
            lines = output.lstrip().splitlines(keepends=True)
            submitted = (
                bool(lines)
                and lines[0].strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
                and rc == 0
            )
            result: dict[str, Any] = {
                "ok": rc == 0,
                "returncode": rc,
                "output": output,
                "submitted": submitted,
                "submission": "".join(lines[1:]) if submitted else "",
            }
            if stream_redactions:
                result["secrets_redacted"] = stream_redactions
            return result
        except OSError as e:
            return {"ok": False, "returncode": -1, "output": "", "error": str(e)}

    def grep_files(args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args["pattern"])
        root_path = _resolve(str(args.get("path") or "."), _root())
        glob_pat = str(args.get("glob") or "")
        max_hits = _safe_int(args.get("max_hits"), 50, minimum=1, maximum=500)
        rg = shutil.which("rg")
        if rg:
            cmd = [rg, "--line-number", "--no-heading", "--color", "never", "--hidden", "-g", "!.git", "-e", pattern]
            if glob_pat:
                cmd.extend(["--glob", glob_pat])
            cmd.append(str(root_path))
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    cwd=_root(),
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                return {"ok": False, "error": str(e), "output": str(e)}
            lines = (proc.stdout or "").splitlines()
            truncated = len(lines) > max_hits
            body = "\n".join(lines[:max_hits]) or "(no matches)"
            if truncated:
                body += "\n… truncated …"
            return {"ok": True, "output": body, "hits": min(len(lines), max_hits), "engine": "rg"}

        try:
            rx = re.compile(pattern)
        except re.error as e:
            return {"ok": False, "error": f"invalid regex: {e}", "output": f"invalid regex: {e}"}
        hits: list[str] = []
        glob_use = glob_pat or "*"
        paths = [root_path] if root_path.is_file() else sorted(root_path.rglob(glob_use))
        for p in paths:
            if not p.is_file():
                continue
            if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p}:{i}:{line[:240]}")
                    if len(hits) >= max_hits:
                        return {
                            "ok": True,
                            "output": "\n".join(hits) + "\n… truncated …",
                            "hits": len(hits),
                            "engine": "python",
                        }
        return {
            "ok": True,
            "output": "\n".join(hits) if hits else "(no matches)",
            "hits": len(hits),
            "engine": "python",
        }

    def glob_files(args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args["pattern"])
        root_path = _resolve(str(args.get("root") or "."), _root())
        matches = []
        for p in sorted(root_path.glob(pattern)):
            if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in p.parts):
                continue
            matches.append(str(p.relative_to(root_path) if p.is_relative_to(root_path) else p))
            if len(matches) >= _safe_int(args.get("max"), 200, minimum=1, maximum=2000):
                matches.append("…")
                break
        return {"ok": True, "output": "\n".join(matches) if matches else "(no matches)", "count": len(matches)}

    def ls_dir(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve(str(args.get("path") or "."), _root())
        if not path.exists():
            return {"ok": False, "error": f"not found: {path}", "output": f"not found: {path}"}
        if path.is_file():
            return {"ok": True, "output": path.name, "count": 1}
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as e:
            return {"ok": False, "error": str(e), "output": str(e)}
        lines = []
        for e in entries:
            if e.name in _SKIP_NAMES:
                continue
            suffix = "/" if e.is_dir() else ""
            lines.append(e.name + suffix)
        return {"ok": True, "output": "\n".join(lines) if lines else "(empty)", "count": len(lines)}

    def load_skill(args: dict[str, Any]) -> dict[str, Any]:
        install = args.get("install")
        installed: list[str] = []
        if install:
            try:
                from kite.skills.install import install_skill
                from kite.skills.loader import load_skills

                installed = install_skill(str(install), link_cwd=project_root)
                for skill in load_skills(project_root):
                    skill_by_name[skill.name] = skill
            except (ValueError, RuntimeError, OSError) as e:
                return {"ok": False, "error": str(e), "output": str(e)}
        name = str(args.get("name") or "").strip()
        if not name and len(installed) == 1:
            name = installed[0]
        if not name:
            if installed:
                listed = ", ".join(installed)
                return {
                    "ok": True,
                    "output": f"installed {listed} into ~/.kite/skills. Load with skill name=…",
                    "installed": installed,
                }
            return {"ok": False, "error": "need name or install", "output": "need name or install"}
        skill = skill_by_name.get(name) or next(
            (s for s in skill_by_name.values() if s.name.lower() == name.lower()),
            None,
        )
        if skill is None:
            known = ", ".join(sorted(skill_by_name)) or "(none)"
            extra = f" installed {', '.join(installed)}." if installed else ""
            return {
                "ok": False,
                "error": f"unknown skill: {name}",
                "output": f"unknown skill: {name}.{extra} known: {known}",
            }
        extra = args.get("instructions")
        text = format_skill_invocation(skill, str(extra) if extra else None)
        prefix = f"installed {', '.join(installed)}.\n\n" if installed else ""
        return {"ok": True, "output": prefix + text, "skill": skill.name, "installed": installed}

    def todo_write(args: dict[str, Any]) -> dict[str, Any]:
        items = args.get("todos") or args.get("items") or []
        if not isinstance(items, list):
            return {"ok": False, "error": "todos must be a list", "output": "todos must be a list"}
        written = store.write(items)
        return _todo_view(written)

    def todo_read(_args: dict[str, Any]) -> dict[str, Any]:
        return _todo_view(store.read())

    def _single_task(prompt: str, glob_pat: str, pattern: Any, root_path: Path) -> str:
        matches = gated("glob", {"pattern": glob_pat, "root": str(root_path), "max": 40}, glob_files)
        parts = [f"task: {prompt}", "files:", matches.get("output") or "(none)"]
        if pattern:
            grepped = gated(
                "grep",
                {"pattern": str(pattern), "path": str(root_path), "max_hits": 30},
                grep_files,
            )
            parts.append("hits:")
            parts.append(str(grepped.get("output") or ""))
        return "\n".join(parts)

    def task_dispatch(args: dict[str, Any]) -> dict[str, Any]:
        """Bounded parallel investigations — glob + optional grep summaries."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        glob_pat = str(args.get("glob") or "**/*.{py,ts,tsx,js,go,rs,md}")
        pattern = args.get("pattern")
        root_path = _resolve(str(args.get("path") or "."), _root())
        prompts = args.get("prompts") or args.get("tasks")
        if isinstance(prompts, list) and prompts:
            sections: list[str] = [f"parallel tasks: {len(prompts)}"]
            with ThreadPoolExecutor(max_workers=min(4, len(prompts))) as pool:
                futures = {
                    pool.submit(_single_task, str(p), glob_pat, pattern, root_path): i
                    for i, p in enumerate(prompts, 1)
                }
                results: dict[int, str] = {}
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        results[idx] = fut.result()
                    except Exception as e:
                        results[idx] = f"task {idx} error: {e}"
            for i in sorted(results):
                sections.append(f"\n--- subagent {i} ---\n{results[i]}")
            text = "\n".join(sections)
        else:
            prompt = str(args.get("prompt") or "")
            text = _single_task(prompt, glob_pat, pattern, root_path)
        if len(text) > 12_000:
            text = text[:12_000] + "\n… summary truncated …"
        return {"ok": True, "output": text, "summary": True, "parallel": bool(prompts)}

    def subagent_run(args: dict[str, Any]) -> dict[str, Any]:
        if orchestrator is None:
            return {"ok": False, "error": "orchestrator not configured", "output": "orchestrator not configured"}
        return orchestrator.dispatch(args)

    def web_search(args: dict[str, Any]) -> dict[str, Any]:
        return websearch(
            str(args.get("query") or ""),
            max_results=int(args.get("max_results") or 8),
        )

    def web_crawl(args: dict[str, Any]) -> dict[str, Any]:
        return webcrawl(
            str(args.get("url") or ""),
            max_pages=int(args.get("max_pages") or 5),
            max_depth=int(args.get("max_depth") or 1),
            same_origin=bool(args.get("same_origin", True)),
        )

    def webfetch(args: dict[str, Any]) -> dict[str, Any]:
        return fetch_url(
            str(args.get("url") or ""),
            timeout=int(args.get("timeout") or 15),
            max_chars=int(args.get("max_chars") or 24_000),
            extract=bool(args.get("extract", True)),
        )

    def set_working_directory(args: dict[str, Any]) -> dict[str, Any]:
        if execution is None:
            msg = "execution session unavailable"
            return {"ok": False, "error": msg, "output": msg}
        target, err = execution.set_cwd(str(args.get("path") or ""))
        if err:
            return {"ok": False, "error": err, "output": err}
        assert target is not None
        return {"ok": True, "cwd": str(target), "output": f"cwd → {target}"}

    def submit_task(args: dict[str, Any]) -> dict[str, Any]:
        """Structured completion — preferred over echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT."""
        message = str(
            args.get("message") or args.get("content") or args.get("submission") or ""
        ).strip()
        if not message:
            return {
                "ok": False,
                "error": "message required — structured summary with Done/Changed/Verification sections",
                "output": "message required",
            }
        return {"ok": True, "submitted": True, "submission": message, "output": message}

    def memory_op(args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "list").lower()
        scope_raw = str(args.get("scope") or "user").lower()
        scope: MemoryScope = "project" if scope_raw == "project" else "user"
        if action == "list":
            notes = mem.notes()
            lines = [f"{n.scope}/{n.id}  {n.text}" for n in notes]
            return {"ok": True, "output": "\n".join(lines) or "(empty memory)", "count": len(notes)}
        if action == "remember":
            text = str(args.get("text") or "").strip()
            if not text:
                return {"ok": False, "error": "text required", "output": "text required"}
            try:
                note = mem.remember(text, scope=scope)
            except ValueError as e:
                return {"ok": False, "error": str(e), "output": str(e)}
            return {"ok": True, "output": f"remembered {note.scope}/{note.id}: {note.text}", "id": note.id}
        if action == "forget":
            query = str(args.get("text") or args.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "text required", "output": "text required"}
            result = mem.forget(query)
            if result.total == 0:
                return {"ok": True, "output": "no matches", "count": 0}
            lines = [f"forgot {n.scope}/{n.id}: {n.text}" for n in result.notes]
            lines.extend(f"forgot episode {e.id}: {e.summary}" for e in result.episodes)
            return {"ok": True, "output": "\n".join(lines), "count": result.total}
        return {"ok": False, "error": "action must be list|remember|forget", "output": "action must be list|remember|forget"}

    reason_prop = {"reason": {"type": "string", "description": "One-line why, shown in the UI"}}

    catalog: list[tuple[str, Tool]] = [
        (
            "read",
            Tool(
                name="read",
                description=(
                    "Bounded file read — fallback when bash peek is not enough. "
                    "Prefer bash (rg, head, sed -n, wc -l) for search and peeking; "
                    "read adds line numbers only when numbered=true. Large files auto-truncate."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer", "description": "1-based start line"},
                        "limit": {"type": "integer", "description": "Max lines to return"},
                        "numbered": {"type": "boolean", "description": "Prefix line numbers (costs tokens)"},
                    },
                    "required": ["path"],
                },
                execute_fn=lambda a: gated("read", a, read_file),
            ),
        ),
        (
            "write",
            Tool(
                name="write",
                description="Create or overwrite a text file. Prefer edit for existing files.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        **reason_prop,
                    },
                    "required": ["path", "content"],
                },
                execute_fn=lambda a: gated("write", a, write_file),
            ),
        ),
        (
            "edit",
            Tool(
                name="edit",
                description="Replace an exact string in a file (unique match unless replace_all). Diff is shown in the UI.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                        "replace_all": {"type": "boolean"},
                        **reason_prop,
                    },
                    "required": ["path", "old", "new"],
                },
                execute_fn=lambda a: gated("edit", a, edit_file),
            ),
        ),
        (
            "bash",
            Tool(
                name="bash",
                description=(
                    "Primary inspection and execution tool. Fresh subprocess each call — "
                    "use set_cwd or cwd= for directory changes. "
                    "Token-efficient reads: rg/grep/find, wc -l, head/tail, sed -n '10,40p', "
                    "cat only for small files. Tests, git, builds, and edits via shell when needed. "
                    "Set background=true for long-running servers; track with /jobs and /kill."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "cwd": {"type": "string", "description": "Working directory (~, relative, or absolute)"},
                        "timeout": {"type": "integer"},
                        "background": {
                            "type": "boolean",
                            "description": "Spawn without waiting; returns job_id (default false)",
                        },
                        **reason_prop,
                    },
                    "required": ["command"],
                },
                execute_fn=lambda a: gated("bash", a, bash),
            ),
        ),
        (
            "grep",
            Tool(
                name="grep",
                description="Convenience content search (wraps rg). Prefer bash `rg` when you need tighter control or piping.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                        "glob": {"type": "string"},
                        "max_hits": {"type": "integer"},
                    },
                    "required": ["pattern"],
                },
                execute_fn=lambda a: gated("grep", a, grep_files),
            ),
        ),
        (
            "glob",
            Tool(
                name="glob",
                description="Convenience file pattern match. Prefer bash `find` or `rg --files` for scoped discovery.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "root": {"type": "string"},
                        "max": {"type": "integer"},
                    },
                    "required": ["pattern"],
                },
                execute_fn=lambda a: gated("glob", a, glob_files),
            ),
        ),
        (
            "ls",
            Tool(
                name="ls",
                description="Convenience directory listing. Prefer bash `ls` when already in a shell chain.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": [],
                },
                execute_fn=lambda a: gated("ls", a, ls_dir),
            ),
        ),
        (
            "set_cwd",
            Tool(
                name="set_cwd",
                description=(
                    "Move the session working directory for all tools and bash defaults. "
                    "Call this when the user names a directory ('go to X and …'). "
                    "Works outside project_root in host mode; sandbox follows the new cwd."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path (~, relative, or absolute)"},
                        **reason_prop,
                    },
                    "required": ["path"],
                },
                execute_fn=lambda a: gated("set_cwd", a, set_working_directory),
            ),
        ),
        (
            "skill",
            Tool(
                name="skill",
                description="Load a named skill, or download one from npm/npx/GitHub into ~/.kite/skills.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill to load"},
                        "instructions": {"type": "string", "description": "Optional extra user instructions"},
                        "install": {
                            "type": "string",
                            "description": "npm/npx package or GitHub owner/repo to download into ~/.kite/skills",
                        },
                    },
                    "required": [],
                },
                execute_fn=lambda a: gated("skill", a, load_skill),
            ),
        ),
        (
            "todo_write",
            Tool(
                name="todo_write",
                description="Replace the live plan checklist. Call this for any multi-step task. statuses: pending | in_progress | completed.",
                parameters={
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "content": {"type": "string"},
                                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                },
                                "required": ["content", "status"],
                            },
                        }
                    },
                    "required": ["todos"],
                },
                execute_fn=lambda a: gated("todo_write", a, todo_write),
            ),
        ),
        (
            "todo_read",
            Tool(
                name="todo_read",
                description="Read the current plan checklist.",
                parameters={"type": "object", "properties": {}},
                execute_fn=lambda a: gated("todo_read", a, todo_read),
            ),
        ),
        (
            "task",
            Tool(
                name="task",
                description="Dispatch bounded investigation(s). Pass `prompt` or `prompts` (list) for parallel sub-searches.",
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "prompts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Run multiple searches in parallel",
                        },
                        "glob": {"type": "string"},
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                    },
                },
                execute_fn=lambda a: gated("task", a, task_dispatch),
            ),
        ),
        (
            "webfetch",
            Tool(
                name="webfetch",
                description=(
                    "Fetch one http(s) URL and return extracted readable text (title + body). "
                    "Use after websearch to read a chosen result. Set extract=false for raw bytes as text."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "timeout": {"type": "integer", "description": "Seconds (default 15)"},
                        "max_chars": {"type": "integer", "description": "Max body chars (default 24000)"},
                        "extract": {
                            "type": "boolean",
                            "description": "Strip HTML to readable text (default true)",
                        },
                    },
                    "required": ["url"],
                },
                execute_fn=lambda a: gated("webfetch", a, webfetch),
            ),
        ),
        (
            "websearch",
            Tool(
                name="websearch",
                description="Search the web (free, no API key). Returns titles, URLs, and snippets. Use before webfetch/webcrawl when you need to find sources.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Max hits (default 8, max 15)"},
                    },
                    "required": ["query"],
                },
                execute_fn=lambda a: gated("websearch", a, web_search),
            ),
        ),
        (
            "webcrawl",
            Tool(
                name="webcrawl",
                description="Crawl a site starting from a URL — fetches pages and extracts text (free, no API key). Prefer webfetch for a single page.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Seed URL"},
                        "max_pages": {"type": "integer", "description": "Max pages to fetch (default 5)"},
                        "max_depth": {"type": "integer", "description": "Link depth from seed (default 1)"},
                        "same_origin": {"type": "boolean", "description": "Stay on same host (default true)"},
                    },
                    "required": ["url"],
                },
                execute_fn=lambda a: gated("webcrawl", a, web_crawl),
            ),
        ),
        (
            "subagent",
            Tool(
                name="subagent",
                description=(
                    "Spawn nested LLM subagent(s) via the orchestrator. "
                    "Pass `prompt` for one worker or `prompts` (list) for parallel workers against the current plan. "
                    "Each subagent has a bounded step budget — use for independent plan items."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "prompts": {"type": "array", "items": {"type": "string"}},
                        "label": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                    },
                },
                execute_fn=lambda a: gated("subagent", a, subagent_run),
            ),
        ),
        (
            "submit",
            Tool(
                name="submit",
                description=(
                    "Finish a build-mode task with a structured summary. "
                    "Use only after verification — include ## Done, ## Changed, and ## Verification sections. "
                    "Preferred over `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Structured final answer (Done / Changed / Verification / Notes)",
                        },
                    },
                    "required": ["message"],
                },
                execute_fn=lambda a: gated("submit", a, submit_task),
            ),
        ),
        (
            "memory",
            Tool(
                name="memory",
                description="List, add, or drop durable notes (user or project). Survives sessions. Not the chat log.",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "remember", "forget"],
                        },
                        "text": {"type": "string", "description": "Note text, or a substring/id to forget"},
                        "scope": {"type": "string", "enum": ["user", "project"]},
                    },
                    "required": ["action"],
                },
                execute_fn=lambda a: gated("memory", a, memory_op),
            ),
        ),
    ]
    return [tool for name, tool in catalog if name in allow]
