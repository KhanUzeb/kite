"""Textual TUI entry and gating."""

from __future__ import annotations

import os
from unittest.mock import patch

from kite.ui.textual.app import should_use_textual_tui


def test_should_use_textual_when_tty_and_not_legacy() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KITE_LEGACY_TUI", None)
        with patch("sys.stdin.isatty", return_value=True):
            assert should_use_textual_tui() is True


def test_legacy_tui_flag_disables_textual() -> None:
    with patch.dict(os.environ, {"KITE_LEGACY_TUI": "1"}):
        with patch("sys.stdin.isatty", return_value=True):
            assert should_use_textual_tui() is False


def test_non_tty_disables_textual() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KITE_LEGACY_TUI", None)
        with patch("sys.stdin.isatty", return_value=False):
            assert should_use_textual_tui() is False
