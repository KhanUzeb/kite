"""Line-ending preservation for file writes (LF/CRLF churn fix).

Root cause it fixes: agent tools read text with universal newlines (CRLF → LF
in memory) and wrote it back with ``Path.write_text`` — on Windows that call
translates every ``\\n`` to ``\\r\\n``, so a one-line edit rewrites the whole
file's endings and git flags every line as modified (balanced insert/delete
diff, empty ``git diff --ignore-space-at-eol``).

Contract:
- Edit an existing file → keep its dominant on-disk ending; only the changed
  region differs. Never re-encode the buffer with the OS default.
- Create a file → OS default (CRLF on Windows, LF on Linux/macOS), unless the
  repo's ``.gitattributes`` (``eol=``) or the nearest ``.editorconfig``
  (``end_of_line=``) says otherwise.
- Writes go through ``write_bytes`` so no layer can re-translate newlines;
  the result is verified by re-reading the raw bytes.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import Path

LF = "\n"
CRLF = "\r\n"


def os_default_ending() -> str:
    """CRLF on Windows, LF everywhere else (new files without repo convention)."""
    return CRLF if sys.platform == "win32" else LF


def detect_line_ending(path: str | Path) -> str | None:
    """Dominant on-disk ending: ``\\r\\n``, ``\\n``, or None.

    None means empty, newline-free, or binary (NUL in the first 8 KiB).
    Ties break toward LF — the git-normalized convention and the safe
    direction (an LF working tree of an LF blob is always clean).
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf == 0 and lf == 0:
        return None
    return CRLF if crlf > lf else LF


def normalize_newlines(text: str) -> str:
    """Fold CRLF and lone CR to LF (in-memory canonical form)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def encode_with_ending(text: str, ending: str) -> bytes:
    """LF-canonical text → bytes with the intended ending (no translation)."""
    normalized = normalize_newlines(text)
    if ending == CRLF:
        normalized = normalized.replace("\n", "\r\n")
    return normalized.encode("utf-8")


def verify_line_endings(path: str | Path, ending: str) -> bool:
    """True when the file's dominant ending matches intent (or is empty)."""
    detected = detect_line_ending(path)
    return detected is None or detected == ending


def _gitattributes_ending(path: Path) -> str | None:
    """Read ``eol``/``text`` for a not-yet-existing path. None = no opinion."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    probe = resolved.parent if resolved.suffix else resolved
    node: Path | None = probe
    repo: Path | None = None
    while node is not None:
        if (node / ".git").exists():
            repo = node
            break
        node = node.parent if node.parent != node else None
    if repo is None:
        return None
    git = _which_git()
    if git is None:
        return None
    try:
        rel = str(resolved.relative_to(repo))
    except ValueError:
        return None
    try:
        proc = subprocess.run(
            [git, "check-attr", "eol", "text", "--", rel],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(repo),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    values: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        # "<path>: <attr>: <value>"
        _, sep, rest = line.partition(": ")
        if not sep:
            continue
        attr, sep2, value = rest.partition(": ")
        if sep2:
            values[attr.strip().lower()] = value.strip().lower()
    if values.get("eol") == "crlf":
        return CRLF
    if values.get("eol") == "lf":
        return LF
    # `text` / `text=auto` normalizes to LF in the repo on commit.
    if values.get("text") in {"set", "auto"}:
        return LF
    return None


def _which_git() -> str | None:
    import shutil

    return shutil.which("git")


def _editorconfig_ending(path: Path) -> str | None:
    """Minimal ``end_of_line`` lookup (nearest file wins, then specificity).

    Supports ``* ? []`` globs (no ``{a,b}`` expansion — those sections are
    skipped). Anything else falls through to the caller default.
    """
    try:
        target = path.expanduser().resolve()
    except OSError:
        return None
    configs: list[tuple[int, Path]] = []  # (distance, file)
    node: Path | None = target.parent if target.suffix else target
    distance = 0
    while node is not None:
        candidate = node / ".editorconfig"
        try:
            if candidate.is_file():
                configs.append((distance, candidate))
        except OSError:
            pass
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace") if candidate.is_file() else ""
        except OSError:
            text = ""
        if _editorconfig_is_root(text):
            break
        node = node.parent if node.parent != node else None
        distance += 1
        if distance > 25:
            break
    best: tuple[int, int, int, str] | None = None  # (distance, -speclen, -order, ending)
    order = 0
    for distance, cfg in configs:
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(target.relative_to(cfg.parent)).replace(os.sep, "/")
        except ValueError:
            continue
        name = target.name
        section: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith((";", "#")):
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip()
                order += 1
                continue
            if section is None:
                continue
            key, sep, value = stripped.partition("=")
            if not sep or key.strip().lower() != "end_of_line":
                continue
            ending = value.strip().lower()
            if ending not in {"lf", "crlf"}:
                continue
            if "{" in section or "}" in section:
                continue
            if _editorconfig_match(section, rel, name):
                candidate_key = (distance, -len(section), -order, ending)
                if best is None or candidate_key < best:
                    best = candidate_key
    if best is None:
        return None
    return CRLF if best[3] == "crlf" else LF


def _editorconfig_is_root(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#")) or stripped.startswith("["):
            continue
        key, sep, value = stripped.partition("=")
        if sep and key.strip().lower() == "root" and value.strip().lower() == "true":
            return True
    return False


def _editorconfig_match(pattern: str, relpath: str, basename: str) -> bool:
    candidates = [relpath]
    if "/" not in pattern.lstrip("/"):
        candidates.append(basename)
    pat = pattern.lstrip("/")
    return any(fnmatch.fnmatchcase(c, pat) for c in candidates)


def new_file_ending(path: str | Path) -> str:
    """Ending for a file being created: gitattributes → editorconfig → OS default."""
    resolved = Path(path)
    return _gitattributes_ending(resolved) or _editorconfig_ending(resolved) or os_default_ending()


def write_text_preserving(path: str | Path, text: str, *, ending: str | None = None) -> str:
    """Write text with an explicit ending via bytes (no OS translation).

    Returns the ending used. Existing files keep their dominant ending;
    new files follow repo convention (LF default). The write is verified
    by re-reading raw bytes; a mismatch rewrites once more (paranoia path).
    """
    target = Path(path)
    chosen = ending
    if chosen is None:
        chosen = detect_line_ending(target) if target.is_file() else None
    if chosen is None:
        chosen = new_file_ending(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_with_ending(text, chosen))
    if not verify_line_endings(target, chosen):
        target.write_bytes(encode_with_ending(text, chosen))
    return chosen
