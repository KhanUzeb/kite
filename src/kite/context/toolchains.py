"""Language toolchain scouting — show the model what it can actually run here.

Finds the project venv python plus system compilers/interpreters
(python, node, npm, uv, cargo, go) with versions, so the model invokes
the right binary directly instead of guessing. Results are cached per
workspace (10 min TTL); each version probe is bounded at 2s so a hung
binary cannot stall context gathering or blow the bench budgets.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROBES: tuple[tuple[str, str], ...] = (
    ("python", "--version"),
    ("node", "--version"),
    ("npm", "--version"),
    ("uv", "--version"),
    ("cargo", "--version"),
    ("go", "version"),
)

_CACHE_TTL_S = 600.0
_CACHE: dict[tuple[str, str], tuple[float, list[Toolchain]]] = {}


@dataclass(frozen=True)
class Toolchain:
    name: str
    path: str
    version: str = ""
    source: str = "path"  # project-venv | active | path


def _probe_version(binary: Path, flag: str) -> str:
    """One-line version output, or '' when the binary hangs/errors."""
    try:
        proc = subprocess.run(
            [str(binary), flag],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    out = (proc.stdout or proc.stderr or "").strip().splitlines()
    return out[0].strip()[:80] if out else ""


def _which(name: str) -> Path | None:
    try:
        found = shutil.which(name)
    except OSError:
        return None
    if not found:
        return None
    try:
        return Path(found).resolve()
    except OSError:
        return None


def scout_toolchains(cwd: str | Path, project_root: str | Path | None = None) -> list[Toolchain]:
    """Toolchains visible from *cwd*: venv python first, then PATH binaries."""
    try:
        cwd_key = str(Path(cwd).expanduser().resolve())
    except OSError:
        cwd_key = str(cwd)
    root_key = str(project_root or "")
    key = (cwd_key, root_key)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and now - cached[0] < _CACHE_TTL_S:
        return list(cached[1])

    found: list[Toolchain] = []
    seen: set[str] = set()

    def _add(name: str, path: Path, source: str, flag: str) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            return
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        found.append(Toolchain(name=name, path=resolved, version=_probe_version(path, flag), source=source))

    try:
        from kite.env.venv import discover_venv, venv_bin_dir

        venv = discover_venv(cwd_key, root_key) if root_key else discover_venv(cwd_key)
        if venv is not None:
            exe = venv_bin_dir(venv) / ("python.exe" if sys.platform == "win32" else "python")
            _add("python", exe, "project-venv", "--version")
    except Exception:
        pass

    try:
        active = Path(sys.executable).resolve()
        _add("python", active, "active", "--version")
    except OSError:
        pass

    for name, flag in _PROBES:
        if name == "python":
            for alias in ("python", "python3"):
                candidate = _which(alias)
                if candidate is not None:
                    _add("python", candidate, "path", "--version")
            continue
        candidate = _which(name)
        if candidate is not None:
            _add(name, candidate, "path", flag)

    _CACHE[key] = (now, found)
    return list(found)


def render_toolchains(items: list[Toolchain], *, max_chars: int = 1_500) -> str:
    """Compact `## Toolchains` section for the run prompt."""
    if not items:
        return ""
    lines = []
    for item in items:
        detail = item.version if item.version.lower().startswith(item.name) else f"{item.name} {item.version}".strip()
        lines.append(f"- {detail} ({item.path}) [{item.source}]")
    text = "## Toolchains\n" + "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n...[truncated]..."
    return text
