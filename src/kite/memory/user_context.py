"""Global user identity files — always ~/.kite/memory/, never per-project."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from kite.config import ensure_home, kite_home
from kite.memory.secure_io import (
    MAX_USER_CONTEXT_CHARS,
    clamp_memory_text,
    secure_memory_write,
    wrap_untrusted_user_content,
)
from kite.memory.working_style import render_working_context

if TYPE_CHECKING:
    from kite.memory.store import MemoryStore

_DEFAULT_USER = """# User

Who you are talking to — name, role, timezone, communication prefs. Edit freely.
"""

_DEFAULT_PROFILE = """# Profile

Longer-lived context: stack, goals, constraints, pet peeves. Edit freely.
"""


def _memory_dir() -> Path:
    ensure_home()
    return kite_home() / "memory"


def user_path() -> Path:
    return _memory_dir() / "USER.md"


def profile_path() -> Path:
    return _memory_dir() / "PROFILE.md"


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_user() -> str:
    raw = _read(user_path())
    if not raw:
        return ""
    return raw if raw != _DEFAULT_USER.strip() else ""


def read_profile() -> str:
    raw = _read(profile_path())
    if not raw:
        return ""
    return raw if raw != _DEFAULT_PROFILE.strip() else ""


def render_user_context(store: MemoryStore, *, max_chars: int = MAX_USER_CONTEXT_CHARS) -> str:
    """Build global identity block: USER + PROFILE + working rhythm."""
    parts: list[str] = []

    user = read_user()
    if user:
        wrapped = wrap_untrusted_user_content(user[:2000], source="USER.md")
        parts.append(f"# User\n{wrapped}")

    profile = read_profile()
    if profile:
        wrapped = wrap_untrusted_user_content(profile[:2000], source="PROFILE.md")
        parts.append(f"# Profile\n{wrapped}")

    working = render_working_context(store, max_chars=max(400, max_chars // 2))
    if working:
        parts.append(working)

    if not parts:
        return ""
    body = "\n\n".join(parts)
    if len(body) > max_chars:
        body = body[: max_chars - 24] + "\n\n...[truncated]..."
    return body


def ensure_defaults() -> None:
    """Create starter USER.md / PROFILE.md if missing."""
    d = _memory_dir()
    d.mkdir(parents=True, exist_ok=True)
    for path, default in ((user_path(), _DEFAULT_USER), (profile_path(), _DEFAULT_PROFILE)):
        if not path.is_file():
            secure_memory_write(path, default)


def _append_line(path: Path, text: str) -> str:
    cleaned = clamp_memory_text(text)
    ensure_defaults()
    raw = _read(path)
    body = raw if raw else (path.name.replace(".md", "").title() + "\n")
    secure_memory_write(path, body.rstrip() + f"\n- {cleaned}\n")
    return cleaned


def append_user_note(text: str) -> str:
    return _append_line(user_path(), text)


def append_profile_note(text: str) -> str:
    return _append_line(profile_path(), text)
