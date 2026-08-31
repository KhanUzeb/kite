"""Workspace sandbox — keep the agent inside the project, off system paths.

The coding tools already resolve paths. Bash is the hole: a `cwd` of C:\\Windows
or `cd / && rm` would ignore the file-tool sandbox. This module is the shared
check for both.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Commands that are never legitimate in a coding-agent workspace.
DANGEROUS_BASH = (
    re.compile(r"(?i)\brm\s+(-[a-z]*f[a-z]*r|-[a-z]*r[a-z]*f)\s+[/\\]"),
    re.compile(r"(?i)\brm\s+-rf\s+[A-Za-z]:\\"),
    re.compile(r"(?i)\b(mkfs|mkfs\.\w+)\b"),
    re.compile(r"(?i)\bformat\s+[A-Za-z]:"),
    re.compile(r"(?i)\bdd\s+if="),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;"),
    re.compile(r"(?i)\b(shutdown|reboot|poweroff|halt)\b"),
    re.compile(r"(?i)\b(stop-computer|restart-computer|restart-service)\b"),
    re.compile(r"(?i)\b(bcdedit|diskpart|cipher\s+/w)\b"),
    re.compile(r"(?i)\b(remove-item|ri)\b.*\b(-recurse|-r)\b.*\b(-force|-fo)\b"),
    re.compile(r"(?i)\bdel\s+/[fqs]+\s+[A-Za-z]:\\"),
    re.compile(r"(?i)\brmdir\s+/s\b"),
    re.compile(r"(?i)\breg\s+(delete|add)\b.*\bHK(LM|CU|U)\\"),
    re.compile(r"(?i)\bnet\s+(user|localgroup|share)\b"),
    re.compile(r"(?i)\b(schtasks|takeown|icacls)\b"),
    re.compile(r"(?i)powershell\s+(-enc|-encodedcommand)\b"),
    re.compile(r"(?i)\b(curl|wget|iwr|invoke-webrequest)\b.*\|\s*(sh|bash|powershell|iex)\b"),
    re.compile(r"(?i)\binvoke-expression\b|\biex\s*\("),
    re.compile(r"(?i)\bgit\s+push\b"),
)

_ABS_PATH = re.compile(
    r"""(?x)
    (?P<path>
        (?:[A-Za-z]:[\\/][^\s'\"|&;<>]*)
        | (?:\\\\[^\s'\"|&;<>]+)
        | (?:~[\\/][^\s'\"|&;<>]+)
        | (?:/(?:etc|usr|bin|sbin|root|var|sys|System|private|home|opt|boot)[^\s'\"|&;<>]*)
    )
    """
)

_CD = re.compile(
    r"(?i)\b(?:cd|chdir|set-location|push-location|sl)\s+(?:/d\s+)?(?P<q>['\"]?)(?P<target>.+?)(?P=q)(?=\s|$|&|\||;)",
)

SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "authorized_keys",
        "NTUSER.DAT",
        "unattend.xml",
    }
)

_GIT_WRITE_BLOCK = frozenset({"hooks", "config", "HEAD", "index"})


def workspace_root(cwd: str | Path) -> Path:
    return Path(cwd).expanduser().resolve()


def resolve_in_workspace(path: str | Path, cwd: str | Path) -> Path:
    p = Path(path).expanduser()
    root = workspace_root(cwd)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def protected_roots() -> list[Path]:
    """System locations the agent must never read or write."""
    roots: list[Path] = []
    home = Path.home()
    extra = [
        home / ".ssh",
        home / ".gnupg",
        home / ".aws",
        home / ".kube",
    ]
    if os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        extra.extend(
            [
                Path(windir),
                Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
                Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
                Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")),
                home / "AppData" / "Roaming" / "Microsoft",
                home / "AppData" / "Local" / "Microsoft",
            ]
        )
    else:
        extra.extend(
            [
                Path("/etc"),
                Path("/usr"),
                Path("/bin"),
                Path("/sbin"),
                Path("/System"),
                Path("/root"),
                Path("/private/etc"),
            ]
        )
    for item in extra:
        try:
            if item.exists():
                roots.append(item.resolve())
        except OSError:
            continue
    return roots


def is_protected(path: Path) -> bool:
    resolved = path.resolve() if path.exists() else path
    name = resolved.name
    if name in SENSITIVE_NAMES:
        return True
    parts = resolved.parts
    if ".git" in parts:
        i = parts.index(".git")
        rest = parts[i + 1 :]
        if rest and rest[0] in _GIT_WRITE_BLOCK:
            return True
    for root in protected_roots():
        try:
            resolved.relative_to(root)
            return True
        except (ValueError, OSError):
            continue
    return False


def clamp_cwd(
    requested: str | None,
    workspace: Path,
    *,
    allow_outside: bool = False,
) -> tuple[Path | None, str]:
    """Return a cwd inside the workspace, or (None, reason)."""
    if not requested or not str(requested).strip():
        return workspace, ""
    try:
        resolved = resolve_in_workspace(requested, workspace)
    except OSError as e:
        return None, f"invalid cwd: {e}"
    if not allow_outside and not is_inside(resolved, workspace):
        return None, f"cwd escapes workspace sandbox ({workspace}): {resolved}"
    if is_protected(resolved):
        return None, f"cwd is a protected path: {resolved}"
    return resolved, ""


def extract_command_paths(command: str) -> list[str]:
    found: list[str] = []
    for match in _ABS_PATH.finditer(command):
        found.append(match.group("path"))
    for match in _CD.finditer(command):
        found.append(match.group("target").strip())
    return found


def check_command_paths(command: str, workspace: Path) -> str:
    """Empty string if ok, else a deny reason."""
    for raw in extract_command_paths(command):
        token = raw.strip().strip("\"'")
        if not token or token in {".", "./", ".\\"}:
            continue
        try:
            resolved = resolve_in_workspace(token, workspace)
        except OSError:
            continue
        if not is_inside(resolved, workspace):
            return f"bash path escapes workspace sandbox ({workspace}): {resolved}"
        if is_protected(resolved):
            return f"bash path is protected: {resolved}"
    return ""


def check_dangerous(command: str) -> str:
    for rx in DANGEROUS_BASH:
        if rx.search(command):
            return f"bash command blocked by sandbox: {rx.pattern}"
    return ""


def cwd_in_trusted(cwd: Path, workspace: Path, trusted: list[str]) -> bool:
    """True when cwd sits inside a configured trusted subtree."""
    if not trusted:
        return False
    try:
        resolved = cwd.expanduser().resolve()
    except OSError:
        return False
    for rel in trusted:
        token = rel.strip().strip("/\\")
        if not token:
            continue
        try:
            root = (workspace / token).resolve()
            if is_inside(resolved, root) or resolved == root:
                return True
        except OSError:
            continue
    return False
