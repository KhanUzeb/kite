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
# Recursive deletes of *relative* project paths are gated by approval, not hard-blocked —
# otherwise a user "approve once" still fails (Windows rmdir / Remove-Item).
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
    re.compile(r"(?i)\bdel\s+/[fqs]+\s+[A-Za-z]:\\"),
    # Absolute / drive-root recursive deletes only (relative project deletes → approval)
    re.compile(r"(?i)\brmdir\s+/s(?:\s+/q)?\s+[\"']?[A-Za-z]:\\"),
    re.compile(
        r"(?i)\brmdir\s+/s(?:\s+/q)?\s+[\"']?/(?:etc|usr|bin|sbin|var|tmp|home|root|System|Library|private)\b"
    ),
    # Note: no \b before -Flag — PowerShell flags are preceded by whitespace (\W), so \b-force never matches.
    re.compile(
        r"(?i)\b(remove-item|ri)\b(?=.*(?:-recurse|-r)\b)(?=.*(?:-force|-fo)\b).*[A-Za-z]:\\"
    ),
    re.compile(
        r"(?i)\b(remove-item|ri)\b(?=.*(?:-recurse|-r)\b)(?!.*(?:-force|-fo)\b).*[A-Za-z]:\\"
    ),
    re.compile(
        r"(?i)\b(remove-item|ri)\b(?=.*(?:-recurse|-r)\b)(?=.*(?:-force|-fo)\b).*"
        r"[\"']?/(?:etc|usr|bin|sbin|var|tmp|home|root|System|Library|private)\b"
    ),
    re.compile(r"(?i)\breg\s+(delete|add)\b.*\bHK(LM|CU|U)\\"),
    re.compile(r"(?i)\bnet\s+(user|localgroup|share)\b"),
    re.compile(r"(?i)\b(schtasks|takeown|icacls)\b"),
    re.compile(r"(?i)powershell(?:\.exe)?\s+(-enc|-encodedcommand|--enc)\b"),
    re.compile(r"(?i)powershell(?:\.exe)?\s+[^\s]*encodedcommand\b"),
    re.compile(r"(?i)\b(curl|wget|iwr|invoke-webrequest)\b.*\|\s*(sh|bash|powershell|iex)\b"),
    re.compile(r"(?i)\b(certutil|bitsadmin)\b"),
    re.compile(r"(?i)\bpip\s+install\b.*\|\s*(sh|bash)\b"),
    re.compile(r"(?i)\bpython(?:3)?\s+-c\b.*\bsocket\b"),
    re.compile(r"(?i)FromBase64String.*\|\s*(iex|invoke-expression)\b"),
    re.compile(r"(?i)\binvoke-expression\s+\$env:"),
    re.compile(r"(?i)\binvoke-expression\b|\biex\s*\("),
    re.compile(r"(?i)\bgit\s+(push|clone)\b"),
    re.compile(r"(?i)\bgit\s+clean\s+-[^\\n]*f"),
    re.compile(r"(?i)\bgit\s+reset\s+--hard\b"),
    re.compile(r"(?i)\bchmod\s+-R\s+/"),
    re.compile(r"(?i)\brm\s+-rf\s+\.\s*$"),
    re.compile(r"(?i)\brm\s+-rf\s+\.\.\s*$"),
    re.compile(r"(?i)\brm\s+-rf\s+~"),
    re.compile(r"(?i)\brm\s+-rf\s+\$HOME\b"),
    re.compile(r"(?i)\brm\s+-rf\s+%USERPROFILE%"),
    re.compile(r"(?i)\brd\s+/s(?:\s+/q)?\b"),
)

# Known tool/cache dirs — auto/yolo may remove these without mandatory approval.
CACHE_DELETE_NAMES = frozenset(
    {
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        ".mypy_cache",
        ".tox",
        ".nox",
        ".hypothesis",
        ".eslintcache",
        "htmlcov",
        ".cache",
        ".pytest-tmp",
        ".pytest-tmp-codex",
        ".coverage",
    }
)

_REC_DELETE_HINT = re.compile(
    r"(?i)\b(rmdir\s+/s|remove-item|\bri\b|rm\s+-\S*r\S*|del\s+/[fqs]+)\b"
)
_PS_FLAG = re.compile(
    r"(?i)^(-recurse|-r|-force|-fo|-literalpath|-path|-include|-exclude|-confirm:\$false|/s|/q|-rf|-fr)$"
)

_ABS_PATH = re.compile(
    r"""(?x)
    (?P<path>
        (?:[A-Za-z]:[\\/][^\s'\"|&;<>]*)
        | (?:[A-Za-z]:[^\s'\"|&;<>]+)
        | (?:\\\\[^\s'\"|&;<>]+)
        | (?:~[\\/][^\s'\"|&;<>]+)
        | (?:\$HOME(?:[\\/][^\s'\"|&;<>]*)?)
        | (?:%[A-Za-z_]+%(?:[\\/][^\s'\"|&;<>]*)?)
        | (?:\.\./[^\s'\"|&;<>]+)
        | (?:/(?:etc|usr|bin|sbin|root|var|sys|System|private|home|opt|boot|data)[^\s'\"|&;<>]*)
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


def is_user_skill_read(path: Path) -> bool:
    """True when *path* resolves inside a user-global skill tree (~/.kite/skills or ~/.agents/skills)."""
    from kite.skills.loader import user_skill_dirs

    try:
        resolved = path.resolve()
    except OSError:
        return False
    roots: list[Path] = []
    for skills_root in user_skill_dirs():
        try:
            roots.append(skills_root.resolve())
            if skills_root.is_dir():
                for child in skills_root.iterdir():
                    try:
                        target = child.resolve()
                        if target.is_dir():
                            roots.append(target)
                    except OSError:
                        continue
        except OSError:
            continue
    for root in roots:
        try:
            if resolved == root or resolved.is_relative_to(root):
                return True
        except (ValueError, OSError):
            continue
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


def _resolve_path_best_effort(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        cur = path.expanduser()
        try:
            while not cur.exists() and cur.parent != cur:
                cur = cur.parent
            if cur.exists():
                return cur.resolve()
        except OSError:
            pass
        return path.expanduser()


def is_protected(path: Path) -> bool:
    resolved = _resolve_path_best_effort(path)
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


def _delete_path_tokens(command: str) -> list[str]:
    """Best-effort path tokens from a recursive delete command."""
    if not _REC_DELETE_HINT.search(command or ""):
        return []
    # Unwrap powershell -Command "..."
    cmd = command.strip()
    m = re.search(r"(?i)powershell(?:\.exe)?\s+(-command|-c)\s+[\"'](.+)[\"']\s*$", cmd)
    if m:
        cmd = m.group(2)
    tokens: list[str] = []
    for raw in re.split(r"[\s,;]+", cmd):
        tok = raw.strip().strip("\"'")
        if not tok or _PS_FLAG.match(tok):
            continue
        if re.match(r"(?i)^(rmdir|rm|del|remove-item|ri|powershell.*)$", tok):
            continue
        if tok.startswith("-") or tok.startswith("/"):
            # Keep absolute Unix paths; drop pure flags like /s /q
            if re.match(r"^/[a-zA-Z]+$", tok):
                continue
            if tok.startswith("-"):
                continue
        tokens.append(tok)
    return tokens


def _is_systemish_delete_target(token: str) -> bool:
    t = token.strip().strip("\"'")
    if not t:
        return False
    if t in {".", "..", "*", "/", "\\"}:
        return True
    if re.match(r"^[A-Za-z]:\\?$", t):
        return True
    if t.startswith("\\\\?\\") or t.startswith("\\\\"):
        return True
    low = t.replace("/", "\\").lower()
    home = str(Path.home()).replace("/", "\\").lower()
    system_prefixes = (
        r"c:\windows",
        r"c:\program files",
        r"c:\programdata",
        r"c:\users\all users",
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/System",
        "/Library",
        "/private",
        "/data",
    )
    if any(low == p or low.startswith(p + "\\") or low.startswith(p + "/") for p in system_prefixes):
        return True
    if low.startswith(r"c:\users\\") and low != home and not low.startswith(home + "\\"):
        return True
    if low.startswith("$home") or low.startswith("%userprofile%"):
        return True
    return False


def is_benign_cache_delete(command: str) -> bool:
    """True when the command only removes known relative tool-cache directories."""
    cmd = (command or "").strip()
    if not cmd or not _REC_DELETE_HINT.search(cmd):
        return False
    tokens = _delete_path_tokens(cmd)
    if not tokens:
        return False
    for tok in tokens:
        if _is_systemish_delete_target(tok):
            return False
        if ".." in Path(tok).parts:
            return False
        name = Path(tok).name.lower()
        # Allow "./.pytest_cache" or ".pytest_cache"
        if name not in {n.lower() for n in CACHE_DELETE_NAMES} and tok.strip("./\\") not in CACHE_DELETE_NAMES:
            # Also allow path ending with cache name
            if not any(tok.replace("\\", "/").rstrip("/").endswith(n) for n in CACHE_DELETE_NAMES):
                return False
    return True


_CHAIN_SPLIT = re.compile(r"\s*&&\s*|\s*;\s*|\s*\|\s*")

_INSPECTION_HEAD = re.compile(
    r"(?i)^\s*("
    r"git\s+(status|diff|log|show|branch|stash\s+list|rev-parse|describe)"
    r"|ls\b|dir\b|cat\b|head\b|tail\b|rg\b|grep\b|find\b|fd\b"
    r"|pwd\b|echo\b|which\b|where\b|type\b|wc\b|file\b|stat\b|tree\b|realpath\b"
    r"|sed\s+-n"
    r"|pytest\b|npm\s+test\b|cargo\s+test\b|go\s+test\b|make\s+test\b"
    r"|node\s+--version|python3?\s+--version|uv\s+--version"
    r")\b"
)

_MUTATING_BASH = re.compile(
    r"(?i)\b("
    r"rm|mv|cp|chmod|chown|mkdir|touch|tee|truncate|install\b"
    r"|sed\s+-i|nano\b|vim?\b|emacs\b"
    r"|git\s+(add|commit|push|reset|checkout|merge|rebase|stash\s+(push|pop|apply)|clean)"
    r"|pip\s+install|npm\s+install|cargo\s+install|apt\s+install|brew\s+install"
    r")\b"
)


def is_inspection_bash(command: str) -> bool:
    """True when bash only explores (read-only). Allowed in plan mode."""
    cmd = (command or "").strip()
    if not cmd:
        return False
    if check_dangerous(cmd):
        return False
    if _MUTATING_BASH.search(cmd):
        return False
    if re.search(r"(?i)(^|[^<])>>?[^>]", cmd):
        return False
    segments = [s.strip() for s in _CHAIN_SPLIT.split(cmd) if s.strip()]
    if not segments:
        return False
    for seg in segments:
        if _CD.match(seg):
            continue
        if not _INSPECTION_HEAD.match(seg):
            return False
    return True


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
