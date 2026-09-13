"""Optional Textual TUI — imported only when KITE_TUI=1 and textual is installed."""

from __future__ import annotations

from kite.ui.tui_gate import should_use_textual_tui

__all__ = ["KiteApp", "run_textual_session", "should_use_textual_tui"]


def __getattr__(name: str):
    if name == "KiteApp":
        from kite.ui.textual.app import KiteApp

        return KiteApp
    if name == "run_textual_session":
        from kite.ui.textual.run import run_textual_session

        return run_textual_session
    raise AttributeError(name)
