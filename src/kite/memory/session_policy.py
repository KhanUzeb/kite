"""Session persistence policy — full, redacted (default), or disabled."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

_VALID = frozenset({"full", "redacted", "disabled"})


def valid_persistence_modes() -> frozenset[str]:
    return _VALID


def persistence_mode() -> str:
    from kite.config.user import UserConfig

    mode = UserConfig.load().session_persistence.strip().lower()
    return mode if mode in _VALID else "redacted"


def persistence_enabled() -> bool:
    return persistence_mode() != "disabled"


def prepare_persisted_value(value: Any) -> Any:
    """Sanitize a value before writing to session JSONL when mode is ``redacted``."""
    mode = persistence_mode()
    if mode == "full":
        return value
    if mode == "disabled":
        return value
    from kite.guardrails.redact import sanitize_value

    return sanitize_value(value)


def prepare_persisted_row(row: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare_persisted_value(row)
    return prepared if isinstance(prepared, dict) else {"value": prepared}


def secure_session_file(path: Path) -> None:
    """Owner read/write only — best effort."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def set_persistence_mode(mode: str) -> str:
    """Persist session_persistence in ~/.kite/config.toml."""
    normalized = mode.strip().lower()
    if normalized not in _VALID:
        allowed = ", ".join(sorted(_VALID))
        raise ValueError(f"session persistence must be one of: {allowed}")
    from kite.config.user import UserConfig

    cfg = UserConfig.load()
    cfg.session_persistence = normalized
    cfg.save()
    return normalized


def persistence_summary() -> dict[str, str]:
    """User-facing summary for CLI/REPL privacy displays."""
    mode = persistence_mode()
    descriptions = {
        "redacted": "recursive secret sanitization before write; chmod 600",
        "full": "raw transcripts on disk (may retain secrets)",
        "disabled": "in-memory only — no session JSONL writes",
    }
    return {
        "session_persistence": mode,
        "session_persistence_detail": descriptions.get(mode, descriptions["redacted"]),
        "skill_trust": "bundled=trusted; npm/git/project/user=untrusted",
        "child_env": "credential-like keys stripped; extra overrides refused",
        "subprocess_teardown": "process groups killed on timeout/cancel",
        "ssrf": "resolve → validate IPs → connect; redirects re-checked",
    }

