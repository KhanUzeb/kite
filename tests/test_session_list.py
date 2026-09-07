"""list_sessions reads only meta rows."""

from __future__ import annotations

from pathlib import Path

from kite.memory.session import create_session, list_sessions


def test_list_sessions_reads_first_line_only(kite_home, monkeypatch) -> None:
    session = create_session(task="demo", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "x" * 5000})
    path = session.path
    assert path is not None

    original_read_text = Path.read_text

    def spy_read_text(self: Path, *args, **kwargs) -> str:
        if self == path:
            raise AssertionError("list_sessions should not read the full session file")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    rows = list_sessions(limit=10)
    assert any(row.id == session.id for row in rows)
