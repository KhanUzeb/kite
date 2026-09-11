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
    root = find_project_root(Path(cwd).expanduser().resolve())
    return [kite_home() / "extensions", root / ".kite" / "extensions"]


def load_extensions(harness: Any, cwd: str | Path = ".") -> list[str]:
    loaded: list[str] = []
    api = ExtensionAPI(harness)
    for directory in extension_dirs(cwd):
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
