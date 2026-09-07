"""Detect project virtualenvs and prepend them to child process PATH."""

from __future__ import annotations

import sys
from pathlib import Path

_VENV_DIR_NAMES = (".venv", "venv")


def _venv_has_python(base: Path) -> bool:
    if sys.platform == "win32":
        scripts = base / "Scripts"
        return (scripts / "python.exe").is_file() or (scripts / "python").is_file()
    return (base / "bin" / "python").is_file()


def discover_venv(*roots: str | Path) -> Path | None:
    """Return the first valid venv under cwd or project root (with pyvenv.cfg)."""
    seen: set[Path] = set()
    for raw in roots:
        try:
            start = Path(raw).expanduser().resolve()
        except OSError:
            continue
        for directory in (start, *start.parents):
            if directory in seen:
                continue
            seen.add(directory)
            for name in _VENV_DIR_NAMES:
                cand = directory / name
                if not cand.is_dir():
                    continue
                if not (cand / "pyvenv.cfg").is_file():
                    continue
                if _venv_has_python(cand):
                    return cand
            if (directory / "pyproject.toml").exists() or (directory / ".git").exists():
                break
    return None


def venv_bin_dir(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def apply_venv(env: dict[str, str], venv: Path | None) -> dict[str, str]:
    if venv is None:
        return env
    out = dict(env)
    bindir = str(venv_bin_dir(venv).resolve())
    path_key = "Path" if sys.platform == "win32" and "Path" in out else "PATH"
    existing = out.get(path_key, "")
    sep = ";" if sys.platform == "win32" else ":"
    out[path_key] = bindir + (sep + existing if existing else "")
    out["VIRTUAL_ENV"] = str(venv.resolve())
    return out


def prepare_child_env(
    *,
    cwd: str | Path,
    project_root: str | Path | None = None,
    venv: Path | None = None,
    extra: dict[str, str] | None = None,
    auto_venv: bool = True,
) -> dict[str, str]:
    """Filtered host env, optionally with project venv prepended to PATH."""
    from kite.guardrails.env_filter import filtered_child_env

    base = filtered_child_env(extra or {"PAGER": "cat", "GIT_PAGER": "cat"})
    if not auto_venv:
        return base
    resolved = venv
    if resolved is None:
        roots: list[Path] = [Path(cwd).expanduser().resolve()]
        if project_root:
            roots.append(Path(project_root).expanduser().resolve())
        resolved = discover_venv(*roots)
    return apply_venv(base, resolved)
