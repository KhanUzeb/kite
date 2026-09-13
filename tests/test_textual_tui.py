"""Textual TUI entry and gating."""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch

from kite.ui.tui_gate import should_use_textual_tui


def test_should_use_textual_when_opted_in() -> None:
    with patch.dict(os.environ, {"KITE_TUI": "1"}, clear=False):
        os.environ.pop("KITE_LEGACY_TUI", None)
        with patch("sys.stdin.isatty", return_value=True):
            sys.modules.setdefault("textual", types.ModuleType("textual"))
            assert should_use_textual_tui() is True


def test_textual_off_by_default() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KITE_TUI", None)
        os.environ.pop("KITE_LEGACY_TUI", None)
        with patch("sys.stdin.isatty", return_value=True):
            assert should_use_textual_tui() is False


def test_legacy_tui_flag_disables_textual() -> None:
    with patch.dict(os.environ, {"KITE_LEGACY_TUI": "1"}):
        with patch("sys.stdin.isatty", return_value=True):
            assert should_use_textual_tui() is False


def test_non_tty_disables_textual() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KITE_LEGACY_TUI", None)
        with patch("sys.stdin.isatty", return_value=False):
            assert should_use_textual_tui() is False
