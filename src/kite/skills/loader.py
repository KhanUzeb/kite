"""Markdown skill loading (Agent Skills / tau-style SKILL.md)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from kite.config import kite_home
from kite.util.cache import TtlCache

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def agents_skills_dir() -> Path:
    """Global Agent Skills library (Cursor/Codex-style ~/.agents/skills)."""
    return Path.home() / ".agents" / "skills"


def user_skill_dirs() -> list[Path]:
    """User-global skill roots — readable outside workspace sandbox."""
    return [kite_home() / "skills", agents_skills_dir()]


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    content: str
    description: str | None = None
    disable_model_invocation: bool = False
    source: str = "bundled"  # bundled | user | project | plugin
    trust: str = "trusted"  # trusted | untrusted
    origin: str = "bundled"  # bundled | user-local | project | npm | git | link | plugin


def skill_trust(source: str, origin: str) -> str:
    """Only bundled skills ship with full trust; everything else is untrusted."""
    if source == "bundled" and origin == "bundled":
        return "trusted"
    return "untrusted"


def _read_provenance(skill_dir: Path) -> str | None:
    prov = skill_dir / ".kite-provenance.json"
    if not prov.is_file():
        return None
    try:
        data = json.loads(prov.read_text(encoding="utf-8"))
        return str(data.get("origin") or "") or None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def origin_for_skill_dir(directory: Path, cwd: Path) -> str:
    source = classify_skill_dir(directory, cwd)
    if source == "bundled":
        return "bundled"
    if source == "project":
        return "project"
    if source == "plugin":
        return "plugin"
    prov = _read_provenance(directory)
    if prov:
        return prov
    return "user-local"


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("\"'")
    return meta, match.group(2)


def _derive_description(content: str) -> str:
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        return s[:160]
    return "No description"


def _load_skill(name: str, path: Path, *, source: str, origin: str) -> Skill:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    trust = skill_trust(source, origin)
    return Skill(
        name=meta.get("name") or name,
        path=path,
        content=body.strip() or raw.strip(),
        description=meta.get("description") or _derive_description(body or raw),
        disable_model_invocation=meta.get("disable-model-invocation", "").lower() == "true",
        source=source,
        trust=trust,
        origin=origin,
    )


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def classify_skill_dir(directory: Path, cwd: Path) -> str:
    try:
        resolved = directory.resolve() if directory.exists() else directory
    except OSError:
        resolved = directory
    home_skills = kite_home() / "skills"
    agents_skills = agents_skills_dir()
    if _is_under(resolved, home_skills) or resolved == home_skills:
        return "user"
    if _is_under(resolved, agents_skills) or resolved == agents_skills:
        return "user"
    if _is_under(resolved, cwd / ".kite" / "skills") or _is_under(resolved, cwd / ".agents" / "skills"):
        return "project"
    text = str(resolved).replace("\\", "/")
    if "/data/skills" in text or text.endswith("data/skills"):
        return "bundled"
    return "plugin"


def _iter_skill_dirs(cwd: Path, extra: list[str] | None = None) -> list[Path]:
    dirs: list[Path] = []
    try:
        bundled = resources.files("kite").joinpath("data/skills")
        dirs.append(Path(str(bundled)))
    except Exception:
        pass
    dirs.append(kite_home() / "skills")
    dirs.append(agents_skills_dir())
    try:
        from kite.plugins.loader import plugin_skill_dirs

        dirs.extend(plugin_skill_dirs(cwd))
    except Exception:
        pass
    dirs.append(cwd / ".kite" / "skills")
    dirs.append(cwd / ".agents" / "skills")
    for e in extra or []:
        dirs.append(Path(e).expanduser())
    seen: set[Path] = set()
    out: list[Path] = []
    for d in dirs:
        try:
            key = d.resolve() if d.exists() else d
        except OSError:
            key = d
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _is_dir(path: Path) -> bool:
    try:
        if path.is_dir():
            return True
        return path.is_symlink() and path.resolve().is_dir()
    except OSError:
        return False


def _is_file(path: Path) -> bool:
    try:
        if path.is_file():
            return True
        return path.is_symlink() and path.resolve().is_file()
    except OSError:
        return False


def _load_from_dir(skills_dir: Path, *, source: str, cwd: Path) -> list[Skill]:
    if not _is_dir(skills_dir):
        return []
    origin = origin_for_skill_dir(skills_dir, cwd)
    skills: list[Skill] = []
    seen: set[str] = set()
    try:
        entries = sorted(skills_dir.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for path in entries:
        skill_path: Path | None = None
        name = path.name
        if _is_dir(path):
            skill_path = path / "SKILL.md"
            if not _is_file(skill_path):
                continue
            item_origin = _read_provenance(path) or origin
        elif _is_file(path) and path.name == "SKILL.md":
            skill_path = path
            name = path.parent.name
            item_origin = _read_provenance(path.parent) or origin
        else:
            continue
        if name in seen:
            continue
        seen.add(name)
        try:
            skills.append(_load_skill(name, skill_path, source=source, origin=item_origin))
        except OSError:
            continue
    return skills


_SKILLS_CACHE: TtlCache[tuple[str, tuple[str, ...]], list[Skill]] = TtlCache(45.0, maxsize=8)


def invalidate_skills() -> None:
    _SKILLS_CACHE.clear()


def load_skills(cwd: str | Path = ".", extra_dirs: list[str] | None = None) -> list[Skill]:
    cwd_path = Path(cwd).expanduser().resolve()
    extra_key = tuple(sorted(extra_dirs or []))
    key = (str(cwd_path), extra_key)
    return _SKILLS_CACHE.get_or_set(key, lambda: _load_skills_uncached(cwd_path, extra_dirs))


def _load_skills_uncached(cwd_path: Path, extra_dirs: list[str] | None = None) -> list[Skill]:
    by_name: dict[str, Skill] = {}
    for d in _iter_skill_dirs(cwd_path, extra_dirs):
        if not _is_dir(d):
            continue
        source = classify_skill_dir(d, cwd_path)
        for skill in _load_from_dir(d, source=source, cwd=cwd_path):
            by_name[skill.name] = skill
    if any(s.source == "bundled" for s in by_name.values()):
        return sorted(by_name.values(), key=lambda s: s.name)
    try:
        bundled = resources.files("kite").joinpath("data/skills")
        if hasattr(bundled, "iterdir"):
            for child in bundled.iterdir():
                skill_file = child.joinpath("SKILL.md")
                if skill_file.is_file():
                    raw = skill_file.read_bytes().decode("utf-8")
                    meta, body = _parse_frontmatter(raw)
                    name = meta.get("name") or child.name
                    existing = by_name.get(name)
                    if existing is not None and existing.source != "bundled":
                        continue
                    if name not in by_name:
                        by_name[name] = Skill(
                            name=name,
                            path=Path(str(skill_file)),
                            content=body.strip() or raw.strip(),
                            description=meta.get("description") or _derive_description(body or raw),
                            disable_model_invocation=meta.get("disable-model-invocation", "").lower()
                            == "true",
                            source="bundled",
                            trust="trusted",
                            origin="bundled",
                        )
    except Exception:
        pass
    return sorted(by_name.values(), key=lambda s: s.name)


def build_skill_index(skills: list[Skill]) -> str:
    visible = [s for s in skills if not s.disable_model_invocation]
    if not visible:
        return "## Available skills\nnone"
    lines = [
        "## Available skills",
        "Read the full skill with the `skill` tool when the task matches its description.",
        "<available_skills>",
    ]
    for s in visible:
        lines.append("  <skill>")
        lines.append(f"    <name>{s.name}</name>")
        lines.append(f"    <description>{s.description or 'No description'}</description>")
        lines.append(f"    <location>{s.path}</location>")
        lines.append(f"    <trust>{s.trust}</trust>")
        lines.append(f"    <origin>{s.origin}</origin>")
        lines.append(f"    <source>{s.source}</source>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def format_skill_invocation(skill: Skill, extra: str | None = None) -> str:
    block = (
        f'<skill name="{skill.name}" location="{skill.path}" trust="{skill.trust}" '
        f'origin="{skill.origin}" source="{skill.source}">\n'
        f"References are relative to {skill.path.parent}.\n\n"
        f"{skill.content.strip()}\n"
        f"</skill>"
    )
    if extra and extra.strip():
        return f"{block}\n\n{extra.strip()}"
    return block


def expand_skill_slash(text: str, skills: list[Skill]) -> str | None:
    stripped = text.strip()
    extra = None
    name = ""
    if stripped.startswith("/skill:"):
        parts = stripped.split(maxsplit=1)
        name = parts[0].removeprefix("/skill:").strip()
        extra = parts[1].strip() if len(parts) > 1 else None
    elif stripped.lower().startswith("/skill ") or stripped.lower() == "/skill":
        rest = stripped[6:].strip()
        if not rest:
            return None
        name, _, tail = rest.partition(" ")
        extra = tail.strip() or None
    else:
        return None
    by_name = {s.name.lower(): s for s in skills}
    key = name.lower()
    if key not in by_name:
        raise KeyError(f"Unknown skill: {name}")
    return format_skill_invocation(by_name[key], extra)
