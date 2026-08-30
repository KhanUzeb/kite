"""Install skills from npm / npx / GitHub into ~/.kite/skills."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from kite.config import ensure_home, kite_home

_SKIP_PREFIX = {
    "npx",
    "npm",
    "npm.cmd",
    "install",
    "i",
    "add",
    "skills",
    "--yes",
    "-y",
}


def user_skills_dir() -> Path:
    ensure_home()
    path = kite_home() / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_install_spec(raw: str) -> tuple[str, str]:
    """Return (kind, ref) — kind is npm or git."""
    tokens = (raw or "").strip().split()
    while tokens and tokens[0].lower().strip(",") in _SKIP_PREFIX:
        tokens.pop(0)
    if not tokens:
        raise ValueError("need an npm package, npx package, or GitHub owner/repo")
    ref = tokens[0].strip()
    if ref.startswith(("npm:", "npx:")):
        return "npm", ref.split(":", 1)[1]
    if ref.startswith(("http://", "https://", "git@")):
        return "git", ref
    if ref.startswith("@") or "/" not in ref:
        return "npm", ref
    # owner/repo
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", ref):
        return "git", f"https://github.com/{ref}.git"
    return "npm", ref


def _safe_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-._")
    if not clean or clean in {".", ".."}:
        raise ValueError(f"unsafe skill name '{name}'")
    return clean


def _which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        return shutil.which(f"{name}.cmd")
    return None


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _folder_skill_name(folder: Path, *, fallback: str | None = None) -> str:
    md = folder / "SKILL.md"
    if md.is_file():
        try:
            from kite.skills.loader import _parse_frontmatter

            meta, _ = _parse_frontmatter(md.read_text(encoding="utf-8"))
            raw = (meta.get("name") or "").strip()
            if raw:
                return _safe_name(raw)
        except OSError:
            pass
    name = folder.name
    if name.lower() in {"package", "dist", "src"} and fallback:
        return _safe_name(fallback.rsplit("/", 1)[-1].lstrip("@"))
    return _safe_name(name)


def _copy_skill_trees(root: Path, dest: Path, *, fallback: str | None = None) -> list[str]:
    found = sorted(
        p
        for p in root.rglob("SKILL.md")
        if "node_modules" not in p.parts and ".git" not in p.parts
    )
    if not found:
        raise RuntimeError("no SKILL.md in that package — not a skill")
    names: list[str] = []
    for skill_md in found:
        folder = skill_md.parent
        name = _folder_skill_name(folder, fallback=fallback)
        target = dest / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(folder, target)
        names.append(name)
    return names


def _from_npm(ref: str, dest: Path) -> list[str]:
    npm = _which("npm")
    if not npm:
        raise RuntimeError("npm not found — install Node.js to fetch npm/npx skills")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        proc = _run([npm, "pack", ref, "--pack-destination", str(tmp_path)])
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "npm pack failed").strip()
            raise RuntimeError(err)
        tgz = next(tmp_path.glob("*.tgz"), None)
        if tgz is None:
            raise RuntimeError(f"npm pack produced no tarball for {ref}")
        unpack = tmp_path / "unpacked"
        unpack.mkdir()
        with tarfile.open(tgz) as tar:
            try:
                tar.extractall(unpack, filter="data")
            except TypeError:
                tar.extractall(unpack)
        return _copy_skill_trees(unpack, dest, fallback=ref)


def _from_git(url: str, dest: Path) -> list[str]:
    git = _which("git")
    if not git:
        raise RuntimeError("git not found — needed to clone skill repos")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        proc = _run([git, "clone", "--depth", "1", "--quiet", url, str(repo)])
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "git clone failed").strip()
            raise RuntimeError(err)
        return _copy_skill_trees(repo, dest, fallback=url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))


def install_skill(spec: str, *, dest: Path | None = None) -> list[str]:
    """Download a skill pack into ~/.kite/skills. Returns installed names."""
    dest = dest or user_skills_dir()
    dest.mkdir(parents=True, exist_ok=True)
    kind, ref = parse_install_spec(spec)
    names = _from_npm(ref, dest) if kind == "npm" else _from_git(ref, dest)
    try:
        from kite.skills.loader import invalidate_skills

        invalidate_skills()
    except Exception:
        pass
    try:
        from kite.cli.slash import invalidate_command_index

        invalidate_command_index()
    except Exception:
        pass
    return names
