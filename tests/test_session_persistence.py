"""Session persistence policy tests."""

from __future__ import annotations

import json
import stat

from kite.config.user import UserConfig
from kite.memory.session import create_session


def _set_persistence(mode: str, kite_home) -> None:
    cfg = UserConfig.load()
    cfg.session_persistence = mode
    cfg.save()


def test_redacted_mode_sanitizes_nested_secrets(kite_home) -> None:
    _set_persistence("redacted", kite_home)
    session = create_session(task="secret", cwd="/tmp", provider="p", model="m")
    session.append(
        {
            "role": "user",
            "content": "Bearer SECRETTOKEN",
            "headers": {"Authorization": "Bearer SECRETTOKEN"},
            "items": [{"token": "SECRETTOKEN"}],
        }
    )
    path = session.path
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "SECRETTOKEN" not in text
    assert "[REDACTED]" in text
    mode = path.stat().st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_full_mode_persists_raw_content(kite_home) -> None:
    _set_persistence("full", kite_home)
    token = "Bearer FULLMODE-SECRET"
    session = create_session(task="full", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": token})
    text = session.path.read_text(encoding="utf-8")
    assert "FULLMODE-SECRET" in text


def test_disabled_mode_skips_file_writes(kite_home) -> None:
    _set_persistence("disabled", kite_home)
    session = create_session(task="off", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "hello"})
    path = session.path
    assert path is not None
    assert not path.is_file() or path.stat().st_size == 0
    assert len(session.messages) == 1


def test_record_event_redacted(kite_home) -> None:
    _set_persistence("redacted", kite_home)
    session = create_session(task="evt", cwd="/tmp", provider="p", model="m")
    session.record_event("tool_end", {"tool": "bash", "args": {"token": "MYSECRET"}})
    lines = session.path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(ln) for ln in lines if '"type": "event"' in ln]
    assert events
    assert "MYSECRET" not in json.dumps(events[-1])
    assert "[REDACTED]" in json.dumps(events[-1])
