"""Pi-style project trust — gate repo-local code until the user approves the workspace."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from kite.config.user import ensure_home, kite_home

_TRUST_FILE = "trust.json"
_PROJECT_MARKER_DIRS = (".kite/plugins", ".kite/extensions")
_PROJECT_TOML = ".kite/project.toml"


def _normalize_root(cwd: str) -> str:
    try:
        return str(Path(cwd).expanduser().resolve())
    except OSError:
        return os.path.abspath(cwd)


def trust_store_path() -> Path:
    return kite_home() / _TRUST_FILE


def _load_store() -> dict[str, dict]:
    path = trust_store_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_store(data: dict[str, dict]) -> None:
    ensure_home()
    path = trust_store_path()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        from kite.memory.session_policy import secure_session_file

        secure_session_file(path)
    except Exception:
        pass


def load_trusted_roots() -> set[str]:
    store = _load_store()
    return {k for k, v in store.items() if isinstance(v, dict) and v.get("trusted")}


def is_project_trusted(cwd: str) -> bool:
    root = _normalize_root(cwd)
    if root in load_trusted_roots():
        return True
    return _project_toml_trust(root)


def _project_toml_trust(root: str) -> bool:
    path = Path(root) / _PROJECT_TOML
    if not path.is_file():
        return False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project") or {}
    if isinstance(project, dict) and project.get("trust") is True:
        return True
    guard = data.get("guardrails") or {}
    if isinstance(guard, dict) and guard.get("project_trust") is True:
        return True
    return False


def project_has_local_code(cwd: str) -> bool:
    root = Path(_normalize_root(cwd))
    for rel in _PROJECT_MARKER_DIRS:
        p = root / rel
        if p.is_dir() and any(p.iterdir()):
            return True
    plugins = root / ".kite" / "plugins"
    if plugins.is_dir():
        for child in plugins.iterdir():
            if child.is_file() and child.suffix in {".py", ".toml"}:
                return True
            if child.is_dir():
                return True
    return False


def project_requires_trust_prompt(cwd: str) -> bool:
    if is_project_trusted(cwd):
        return False
    return project_has_local_code(cwd)


def mark_project_trusted(cwd: str, *, note: str = "") -> Path:
    root = _normalize_root(cwd)
    store = _load_store()
    store[root] = {"trusted": True, "note": note[:200]}
    _save_store(store)
    return trust_store_path()


def revoke_project_trust(cwd: str) -> bool:
    root = _normalize_root(cwd)
    store = _load_store()
    if root not in store:
        return False
    del store[root]
    _save_store(store)
    return True


def project_approval_overlay(cwd: str) -> dict[str, str]:
    """Optional approval hints from .kite/project.toml."""
    path = Path(_normalize_root(cwd)) / _PROJECT_TOML
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out: dict[str, str] = {}
    project = data.get("project") or {}
    if isinstance(project, dict):
        if project.get("approval"):
            out["approval"] = str(project["approval"])
        if project.get("nested_agents") == "auto":
            out["nested_agents"] = "auto"
    guard = data.get("guardrails") or {}
    if isinstance(guard, dict) and guard.get("approval"):
        out["approval"] = str(guard["approval"])
    return out


def skips_nested_agent_approval(cwd: str | None) -> bool:
    """Trusted projects skip nested-agent approval prompts (Pi/Codex-style)."""
    if not cwd:
        return False
    if not is_project_trusted(cwd):
        return False
    overlay = project_approval_overlay(cwd)
    if overlay.get("nested_agents") == "prompt":
        return False
    return True


def without_nested_agent_if_trusted(
    effects: set[str],
    workspace_cwd: str | None,
) -> set[str]:
    """Drop nested_agent from mandatory effects when the workspace is trusted."""
    if "nested_agent" not in effects or not skips_nested_agent_approval(workspace_cwd):
        return effects
    out = set(effects)
    out.discard("nested_agent")
    return out
