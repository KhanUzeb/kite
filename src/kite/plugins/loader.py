"""Kite plugins — a folder of commands + skills with a small manifest."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from kite.commands.loader import PromptCommand, load_commands_from_dir
from kite.config import kite_home
from kite.context.discovery import find_project_root

PLUGIN_TOML = """\
name = "{name}"
description = ""
version = "0.1.0"
"""


@dataclass(frozen=True)
class Plugin:
    name: str
    description: str
    version: str
    path: Path
    source: str  # user | project
    commands: tuple[PromptCommand, ...] = field(default_factory=tuple)

    @property
    def skills_dir(self) -> Path:
        return self.path / "skills"


def user_plugins_dir() -> Path:
    return kite_home() / "plugins"


def project_plugins_dir(cwd: str | Path) -> Path:
    root = find_project_root(Path(cwd).expanduser().resolve())
    return root / ".kite" / "plugins"


def _read_manifest(path: Path) -> dict:
    toml_path = path / "plugin.toml"
    if toml_path.is_file():
        try:
            return tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}
    json_path = path / "plugin.json"
    if json_path.is_file():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _load_plugin(path: Path, *, source: str) -> Plugin | None:
    if not path.is_dir():
        return None
    commands_dir = path / "commands"
    skills_dir = path / "skills"
    manifest = _read_manifest(path)
    if not manifest and not commands_dir.is_dir() and not skills_dir.is_dir():
        return None
    name = str(manifest.get("name") or path.name).strip()
    if not name:
        return None
    commands = tuple(
        load_commands_from_dir(commands_dir, source="plugin", plugin=name) if commands_dir.is_dir() else ()
    )
    return Plugin(
        name=name,
        description=str(manifest.get("description") or ""),
        version=str(manifest.get("version") or ""),
        path=path,
        source=source,
        commands=commands,
    )


def _iter_plugin_roots(root: Path, *, source: str) -> list[Plugin]:
    if not root.is_dir():
        return []
    found: list[Plugin] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for child in children:
        plugin = _load_plugin(child, source=source)
        if plugin is not None:
            found.append(plugin)
    return found


def load_plugins(cwd: str | Path) -> list[Plugin]:
    """User plugins first, project plugins later (later wins on command name)."""
    cwd_path = Path(cwd).expanduser().resolve()
    by_name: dict[str, Plugin] = {}
    for plugin in _iter_plugin_roots(user_plugins_dir(), source="user"):
        by_name[plugin.name] = plugin
    for plugin in _iter_plugin_roots(project_plugins_dir(cwd_path), source="project"):
        by_name[plugin.name] = plugin
    return sorted(by_name.values(), key=lambda p: p.name.lower())


def plugin_skill_dirs(cwd: str | Path) -> list[Path]:
    dirs: list[Path] = []
    for plugin in load_plugins(cwd):
        if plugin.skills_dir.is_dir():
            dirs.append(plugin.skills_dir)
    return dirs


def write_plugin_stub(directory: Path, name: str) -> Path:
    clean = name.strip().lstrip("/").replace(" ", "-")
    if not clean:
        raise ValueError("plugin name required")
    root = directory / clean
    if root.exists():
        raise FileExistsError(str(root))
    (root / "commands").mkdir(parents=True)
    (root / "skills").mkdir(parents=True)
    (root / "plugin.toml").write_text(PLUGIN_TOML.format(name=clean), encoding="utf-8")
    return root
