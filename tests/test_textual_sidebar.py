"""Textual sidebar panels."""

from __future__ import annotations

from unittest.mock import MagicMock

from kite.ui.textual.sidebar import Sidebar


def test_sidebar_changes_clean_repo() -> None:
    session = MagicMock()
    session.cwd = "."
    session._session_id = ""
    session.jobs.list.return_value = []
    bar = Sidebar(session)
    text = bar._render_changes()
    assert "Changes" in text
