"""Session list formatting and search."""

from __future__ import annotations

import time

from kite.memory.session import create_session, list_sessions
from kite.memory.session_format import (
    format_session_picker_label,
    format_session_resume_hint,
    format_session_when,
    match_sessions,
    session_title,
    suggest_sessions,
)


def test_session_title_prefers_label(kite_home) -> None:
    session = create_session(
        task="long task text",
        cwd="/tmp",
        provider="p",
        model="m",
        label="Humanize docs",
    )
    assert session_title(session.meta) == "Humanize docs"


def test_format_session_when_relative() -> None:
    now = time.time()
    _, _, rel = format_session_when(now - 120, now=now)
    assert rel == "2m ago"


def test_match_sessions_by_title(kite_home) -> None:
    create_session(task="alpha", cwd="/tmp", provider="p", model="m", label="docs cleanup")
    create_session(task="beta", cwd="/tmp", provider="p", model="m", label="tests only")
    rows = list_sessions(limit=10)
    matched = match_sessions(rows, "docs")
    assert len(matched) == 1
    assert "docs" in session_title(matched[0]).lower()


def test_list_sessions_query_filter(kite_home) -> None:
    create_session(task="one", cwd="/tmp/proj", provider="p", model="m", label="refactor auth")
    create_session(task="two", cwd="/tmp/other", provider="p", model="m", label="fix typo")
    rows = list_sessions(limit=10, query="auth")
    assert len(rows) == 1
    assert "auth" in session_title(rows[0]).lower()


def test_picker_label_includes_date_and_short_id(kite_home) -> None:
    session = create_session(task="ship it", cwd="/tmp/kite", provider="groq", model="llama", label="ship")
    label = format_session_picker_label(session.meta)
    assert "groq/llama" in label
    assert session.id.split("-")[-1] in label
    assert any(ch.isdigit() for ch in label)


def test_resume_hint_and_suggestions(kite_home) -> None:
    session = create_session(task="humanize readme", cwd="/tmp", provider="p", model="m")
    hint = format_session_resume_hint(session.meta)
    assert "humanize readme" in hint
    short = session.id.split("-")[-1]
    found = suggest_sessions(short, limit=3)
    assert any(row.id == session.id for row in found)
