"""Shared BYOS authentication types and helpers."""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rich.console import Console

_TOKEN_PATTERN = re.compile(
    r"(?i)(?:"
    r"access[_-]?token|refresh[_-]?token|authorization|bearer|"
    r"sk-ant-oat[a-z0-9_-]*"
    r")"
)
_JWT_PATTERN = re.compile(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")


@dataclass(frozen=True)
class AuthStatus:
    """Provider authentication state — never includes secrets."""

    authenticated: bool
    message: str
    account_label: str = ""
    method: str = ""  # e.g. subscription, api_key, device


@dataclass(frozen=True)
class LoginResult:
    exit_code: int
    message: str


def sanitize_auth_message(text: str) -> str:
    """Strip token-shaped substrings from user-facing auth errors."""
    if not text:
        return text
    cleaned = _JWT_PATTERN.sub("[redacted]", text)
    cleaned = _TOKEN_PATTERN.sub("[redacted]", cleaned)
    cleaned = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"access_token=\S+", "access_token=[redacted]", cleaned, flags=re.IGNORECASE)
    return cleaned


def secure_path(path: Path) -> None:
    """Owner read/write only — best effort."""
    if path.is_file():
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON metadata atomically with restrictive permissions."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{id(path)}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    secure_path(tmp)
    tmp.replace(path)
    secure_path(path)


@runtime_checkable
class AuthProvider(Protocol):
    """Provider-specific BYOS authentication surface."""

    provider_key: str

    def status(self) -> AuthStatus: ...

    def login(self, *, device: bool = False, console: Console | None = None) -> LoginResult: ...

    def logout(self) -> bool: ...

    def fetch_model_ids(self) -> tuple[str, ...]: ...

    def litellm_env(self) -> dict[str, str]: ...

    def litellm_extras(self) -> dict[str, object]: ...
