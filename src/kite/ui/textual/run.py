"""Launch the Textual Kite session."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kite.ui.repl import ChatSession


def run_textual_session(session: ChatSession) -> int:
    from kite.ui.textual.app import KiteApp

    if session._pending_open:
        session._open_session(session._pending_open)
        session._pending_open = None

    app = KiteApp(session)
    try:
        app.run()
    finally:
        session._teardown_jobs()
    return 0
