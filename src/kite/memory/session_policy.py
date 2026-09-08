"""Session persistence policy — full, redacted (default), or disabled."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

_VALID = frozenset({"full", "redacted", "disabled"})


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
