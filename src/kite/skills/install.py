"""Install skills from npm / npx / GitHub into ~/.kite/skills."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path

from kite.config import ensure_home, kite_home
from kite.guardrails.env_filter import filtered_child_env

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
    """Return (kind, ref) — kind is npm, git, or link."""
    tokens = (raw or "").strip().split()
    while tokens and tokens[0].lower().strip(",") in _SKIP_PREFIX:
        tokens.pop(0)
    if not tokens:
        raise ValueError("need an npm package, npx package, GitHub owner/repo, or local path")
    ref = tokens[0].strip()
    local = _local_skill_path(ref)
    if local is not None:
        return "link", str(local)
    if ref.startswith(("npm:", "npx:")):
        return "npm", ref.split(":", 1)[1]
    if ref.startswith(("http://", "https://", "git@")):
        return "git", ref
    if ref.startswith("@") or "/" not in ref:
        return "npm", ref
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", ref):
        return "git", f"https://github.com/{ref}.git"
    return "npm", ref


def _local_skill_path(ref: str) -> Path | None:
    """Absolute/relative/home path to a skill dir or SKILL.md, else None."""
    looks = ref.startswith(("./", ".\\", "../", "..\\", "~/", "~\\")) or Path(ref).is_absolute()
    candidate = Path(ref).expanduser()
    if not looks and not candidate.exists():
        return None
    if candidate.is_file() and candidate.name == "SKILL.md":
        return candidate.parent
    if candidate.is_dir() or looks:
        return candidate
    return None


def _is_link_or_junction(target: Path) -> bool:
    try:
        if target.is_symlink():
            return True
    except OSError:
        return False
    try:
        attrs = getattr(os.lstat(target), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _remove_skill_target(target: Path) -> None:
    """Drop a previous install without following a link into the real tree."""
    if _is_link_or_junction(target) or target.is_file():
        try:
            target.unlink()
        except OSError:
            os.rmdir(target)
        return
    if target.is_dir():
        shutil.rmtree(target)


def _windows_junction(link: Path, source: Path) -> bool:
    if os.name != "nt" or not source.is_dir():
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(source)],
        capture_output=True,
        text=True,
        creationflags=flags,
    )
    return proc.returncode == 0 and (link.exists() or _is_link_or_junction(link))


def symlink_or_copy(link: Path, source: Path) -> str:
    """Link *link* → *source*. Junction on Windows if needed; copy as last resort."""
    source = source.expanduser().resolve()
    link.parent.mkdir(parents=True, exist_ok=True)
    _remove_skill_target(link)
    try:
        link.symlink_to(source, target_is_directory=source.is_dir())
        return "link"
    except OSError:
        pass
    if _windows_junction(link, source):
        return "link"
    if source.is_dir():
        shutil.copytree(source, link, symlinks=True)
    else:
        shutil.copy2(source, link)
    return "copy"


def link_into_project(names: list[str], *, dest: Path, cwd: Path | None) -> None:
    """Point <cwd>/.kite/skills/<name> at the global install when cwd is a project."""
    if cwd is None:
        return
    project_skills = Path(cwd).expanduser().resolve() / ".kite" / "skills"
    project_skills.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = dest / name
        if not src.exists() and not src.is_symlink():
            continue
        symlink_or_copy(project_skills / name, src)


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


def _write_provenance(skill_dir: Path, origin: str, ref: str) -> None:
    from kite.providers.auth.base import atomic_write_json

    atomic_write_json(skill_dir / ".kite-provenance.json", {"origin": origin, "ref": ref})


def _tag_installed(dest: Path, names: list[str], origin: str, ref: str) -> None:
    for name in names:
        _write_provenance(dest / name, origin, ref)


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=filtered_child_env(),
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


def _find_skill_mds(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", ".git"}]
        if "SKILL.md" in filenames:
            found.append(Path(dirpath) / "SKILL.md")
    return sorted(found)


def _copy_skill_trees(root: Path, dest: Path, *, fallback: str | None = None) -> list[str]:
    found = _find_skill_mds(root)
    if not found:
        raise RuntimeError("no SKILL.md in that package — not a skill")
    names: list[str] = []
    for skill_md in found:
        folder = skill_md.parent
        name = _folder_skill_name(folder, fallback=fallback)
        target = dest / name
        _remove_skill_target(target)
        shutil.copytree(folder, target, symlinks=True)
        names.append(name)
    return names


def _from_path(src: Path, dest: Path) -> list[str]:
    src = src.expanduser()
    if not src.exists():
        raise RuntimeError(f"skill path not found: {src}")
    if src.is_file() and src.name == "SKILL.md":
        src = src.parent
    md = src / "SKILL.md"
    if md.is_file() or md.is_symlink():
        name = _folder_skill_name(src)
        symlink_or_copy(dest / name, src)
        return [name]
    return _copy_skill_trees(src, dest, fallback=src.name)


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


def install_skill(
    spec: str,
    *,
    dest: Path | None = None,
    link_cwd: Path | str | None = None,
) -> list[str]:
    """Install a skill pack into ~/.kite/skills. Returns installed names.

    npm/git packs are copied. A local path is symlinked into the global dir
    (copied if the OS refuses links). When *link_cwd* is set, each name is also
    linked from ``<cwd>/.kite/skills``.
    """
    dest = dest or user_skills_dir()
    dest.mkdir(parents=True, exist_ok=True)
    kind, ref = parse_install_spec(spec)
    if kind == "npm":
        names = _from_npm(ref, dest)
        _tag_installed(dest, names, "npm", ref)
    elif kind == "git":
        names = _from_git(ref, dest)
        _tag_installed(dest, names, "git", ref)
    else:
        names = _from_path(Path(ref), dest)
        _tag_installed(dest, names, "link", ref)
    cwd = Path(link_cwd) if link_cwd else None
    link_into_project(names, dest=dest, cwd=cwd)
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
