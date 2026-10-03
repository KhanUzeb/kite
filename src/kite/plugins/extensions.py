"""Load user/project Python extensions that register against the harness."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from kite.config import kite_home
from kite.context.discovery import find_project_root


class ExtensionAPI:
    """What `register(kite)` receives — same surface as Harness.use / Harness.on."""

    def __init__(self, harness: Any) -> None:
        self._harness = harness

    def use(self, slot: str, impl: Any) -> ExtensionAPI:
        self._harness.use(slot, impl)
        return self

    def on(self, event: str, fn=None):
        if fn is None:
            return lambda f: self._harness.on(event, f)
        self._harness.on(event, fn)
        return fn

    def register_tool(self, tool: Any) -> ExtensionAPI:
        self._harness.extra_tools.append(tool)
        return self


def extension_dirs(cwd: str | Path = ".") -> list[Path]:
    return [global_extension_dir(), project_extension_dir(cwd)]


def global_extension_dir() -> Path:
    return kite_home() / "extensions"


def project_extension_dir(cwd: str | Path = ".") -> Path:
    root = find_project_root(Path(cwd).expanduser().resolve())
    return root / ".kite" / "extensions"


def _project_is_trusted(cwd: str | Path, trusted: bool | None) -> bool:
    if trusted is not None:
        return bool(trusted)
    try:
        from kite.guardrails.project_trust import is_project_trusted
    except Exception:
        return False
    try:
        return bool(is_project_trusted(str(cwd)))
    except Exception:
        return False


def load_extensions(
    harness: Any,
    cwd: str | Path = ".",
    *,
    require_trust: bool = True,
    trusted: bool | None = None,
) -> list[str]:
    """Exec global extensions always; gate project-local ones behind trust.

    Project ``.kite/extensions`` only loads when ``require_trust`` is False
    or the workspace is trusted (fail-closed: unknown trust skips project
    code, so headless runs never exec untrusted project modules).
    """
    directories = [global_extension_dir()]
    if not require_trust or _project_is_trusted(cwd, trusted):
        project_dir = project_extension_dir(cwd)
        if project_dir not in directories:
            directories.append(project_dir)
    loaded: list[str] = []
    api = ExtensionAPI(harness)
    for directory in directories:
        if not directory.is_dir():
            continue
        try:
            files = sorted(directory.glob("*.py"))
        except OSError:
            continue
        for path in files:
            if path.name.startswith("_"):
                continue
            name = f"kite_ext_{directory.name}_{path.stem}"
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
                register = getattr(module, "register", None)
                if callable(register):
                    register(api)
                    loaded.append(str(path))
            except Exception:
                sys.modules.pop(name, None)
    return loaded
