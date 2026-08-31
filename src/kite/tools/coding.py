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
from urllib.error import URLError
from urllib.request import Request, urlopen

from kite.guardrails import GuardrailPolicy, redact_secrets
from kite.memory.store import MemoryStore
from kite.skills.loader import Skill, format_skill_invocation
from kite.tools import Tool
from kite.tools.store import TodoStore
from kite.tools.web import webcrawl, websearch

try:
    from kite.context.workspace import ExecutionSession
except ImportError:  # pragma: no cover
    ExecutionSession = None  # type: ignore[misc, assignment]

try:
    from kite.agent.cancel import CancelToken
except ImportError:  # pragma: no cover
    CancelToken = None  # type: ignore[misc, assignment]


_SKIP_NAMES = frozenset({".git", ".venv", "node_modules", "__pycache__"})


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
) -> list[Tool]:
    def _root() -> str:
        if execution is not None:
            return str(execution.execution_cwd)
        return cwd or os.getcwd()

    root = _root()
    project_root = str(execution.project_root) if execution is not None else (cwd or os.getcwd())
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
        start = int(args.get("offset", 1))
        limit = args.get("limit")
        lines = text.splitlines(keepends=True)
        chunk = lines[start - 1 :] if start > 1 else lines
        if limit is not None:
            chunk = chunk[: int(limit)]
        numbered = "".join(f"{i + start:6}|{line}" for i, line in enumerate(chunk))
        truncated = False
        if limit is None and len(lines) > 800:
            numbered = "".join(f"{i + start:6}|{line}" for i, line in enumerate(lines[:400]))
            numbered += f"\n... [{len(lines) - 400} lines truncated; pass offset/limit] ...\n"
            truncated = True
        return {"ok": True, "path": str(path), "output": numbered, "truncated": truncated}

    def write_file(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve(str(args["path"]), _root())
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
        }

    def edit_file(args: dict[str, Any]) -> dict[str, Any]:
        path = _resolve(str(args["path"]), _root())
        if path.is_dir():
            msg = f"cannot edit: {path} is a directory"
            return {"ok": False, "error": msg, "path": str(path), "output": msg}
        old, new = str(args["old"]), str(args["new"])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return _io_fail(path, e)
        count = text.count(old)
        if count == 0:
            return {"ok": False, "error": "old string not found", "path": str(path), "output": "old string not found"}
        if count > 1 and not args.get("replace_all"):
            msg = f"old string found {count} times; pass replace_all=true or make it unique"
            return {"ok": False, "error": msg, "path": str(path), "output": msg}
        after = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
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
        }

    def bash(args: dict[str, Any]) -> dict[str, Any]:
        command = str(args["command"])
        workdir = str(args.get("cwd") or _root())
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
        except Exception:
            workdir = _root()
        try:
            limit = int(args.get("timeout") or timeout)
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=os.environ | {"PAGER": "cat", "GIT_PAGER": "cat"},
            )
            output_parts: list[str] = []
            stream_redactions = 0

            def _emit_line(raw_line: str) -> None:
                nonlocal stream_redactions
                safe, n = redact_secrets(raw_line)
                stream_redactions += n
                output_parts.append(safe)
                try:
                    sys.stderr.write(safe)
                    sys.stderr.flush()
                except OSError:
                    pass

            def _drain() -> None:
                assert proc.stdout is not None
                for line in iter(proc.stdout.readline, ""):
                    _emit_line(line)

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
            except OSError:
                raise
            reader.join(timeout=2.0)
            output = "".join(output_parts)
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
        max_hits = int(args.get("max_hits") or 50)
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

        rx = re.compile(pattern)
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
            if len(matches) >= int(args.get("max") or 200):
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

                installed = install_skill(str(install))
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
        matches = glob_files({"pattern": glob_pat, "root": str(root_path), "max": 40})
        parts = [f"task: {prompt}", "files:", matches.get("output") or "(none)"]
        if pattern:
            grepped = grep_files({"pattern": str(pattern), "path": str(root_path), "max_hits": 30})
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
        url = str(args["url"])
        if not url.startswith(("https://", "http://")):
            return {"ok": False, "error": "only http(s) URLs allowed", "output": "only http(s) URLs allowed"}
        req = Request(url, headers={"User-Agent": "kite-agent/0.4"})
        try:
            with urlopen(req, timeout=int(args.get("timeout") or 15)) as resp:  # noqa: S310
                raw = resp.read(80_000)
                charset = "utf-8"
                ctype = resp.headers.get_content_charset()
                if ctype:
                    charset = ctype
                text = raw.decode(charset, errors="replace")
        except (URLError, OSError, TimeoutError, ValueError) as e:
            return {"ok": False, "error": str(e), "output": str(e)}
        if len(text) > 40_000:
            text = text[:20_000] + "\n...<truncated>...\n" + text[-8_000:]
        return {"ok": True, "output": text, "url": url}

    def set_working_directory(args: dict[str, Any]) -> dict[str, Any]:
        if execution is None:
            msg = "execution session unavailable"
            return {"ok": False, "error": msg, "output": msg}
        target, err = execution.set_cwd(str(args.get("path") or ""))
        if err:
            return {"ok": False, "error": err, "output": err}
        assert target is not None
        return {"ok": True, "cwd": str(target), "output": f"cwd → {target}"}

    def memory_op(args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "list").lower()
        scope = str(args.get("scope") or "user").lower()
        if scope not in {"user", "project"}:
            scope = "user"
        if action == "list":
            notes = mem.notes()
            lines = [f"{n.scope}/{n.id}  {n.text}" for n in notes]
            return {"ok": True, "output": "\n".join(lines) or "(empty memory)", "count": len(notes)}
        if action == "remember":
            text = str(args.get("text") or "").strip()
            if not text:
                return {"ok": False, "error": "text required", "output": "text required"}
            try:
                note = mem.remember(text, scope=scope)  # type: ignore[arg-type]
            except ValueError as e:
                return {"ok": False, "error": str(e), "output": str(e)}
            return {"ok": True, "output": f"remembered {note.scope}/{note.id}: {note.text}", "id": note.id}
        if action == "forget":
            query = str(args.get("text") or args.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "text required", "output": "text required"}
            removed = mem.forget(query)
            if not removed:
                return {"ok": True, "output": "no matching notes", "count": 0}
            lines = [f"forgot {n.scope}/{n.id}: {n.text}" for n in removed]
            return {"ok": True, "output": "\n".join(lines), "count": len(removed)}
        return {"ok": False, "error": "action must be list|remember|forget", "output": "action must be list|remember|forget"}

    reason_prop = {"reason": {"type": "string", "description": "One-line why, shown in the UI"}}

    catalog: list[tuple[str, Tool]] = [
        (
            "read",
            Tool(
                name="read",
                description="Read a text file. Optional 1-based offset and line limit. Huge files auto-truncate. Directories are listed (use ls, or read a file inside).",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit": {"type": "integer"},
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
                description="Run a shell command in a fresh subprocess (state does not persist). Highest privilege — gated.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "cwd": {"type": "string"},
                        "timeout": {"type": "integer"},
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
                description="Search file contents. Uses ripgrep (rg) when installed.",
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
                description="List files matching a glob pattern under root.",
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
                description="List a directory (names only, dirs end with /).",
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
                description="Change the session working directory for file tools and bash (default cwd).",
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
                description="Fetch a single URL (http/https) and return truncated text. For docs and issues mid-task.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "timeout": {"type": "integer"},
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
