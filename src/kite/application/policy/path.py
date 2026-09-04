"""Path containment policy — wraps guardrails sandbox."""

from __future__ import annotations

from pathlib import Path

from kite.guardrails.sandbox import is_inside, protected_roots, resolve_in_workspace


def check_path_access(path: str | Path, workspace: str | Path, *, write: bool = False) -> tuple[bool, str]:
    """Return (allowed, reason) for filesystem access."""
    root = Path(workspace).expanduser().resolve()
    try:
        resolved = resolve_in_workspace(path, root)
    except Exception as exc:
        return False, str(exc)

    if not is_inside(resolved, root):
        return False, f"path outside workspace: {resolved}"

    for prot in protected_roots():
        try:
            if resolved == prot.resolve() or resolved.is_relative_to(prot.resolve()):
                return False, f"protected path: {resolved}"
        except (ValueError, OSError):
            continue

    # Sibling-prefix trap: C:\proj-evil when workspace is C:\proj
    root_str = str(root)
    resolved_str = str(resolved)
    if not resolved_str.startswith(root_str):
        return False, "sibling-prefix escape"

    return True, "ok"


def check_traversal_cases(workspace: Path) -> list[tuple[str, bool]]:
    """Canonical containment cases for regression tests."""
    ws = workspace.resolve()
    cases: list[tuple[str, bool]] = []
    cases.append(("../outside", False))
    cases.append((".", True))
    cases.append(("src/../src", True))
    if (ws / "link").exists():
        cases.append(("link", True))
    return cases
