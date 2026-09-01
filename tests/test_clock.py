"""Session time injection."""

from __future__ import annotations

from kite.context.clock import session_time_section


def test_session_time_section_has_utc_and_local() -> None:
    text = session_time_section()
    assert "## Session time" in text
    assert "UTC:" in text
    assert "Local:" in text
