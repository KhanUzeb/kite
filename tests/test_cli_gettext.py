"""Behavior tests for the scoped argparse-gettext fast path."""

from __future__ import annotations

import argparse
import gettext

from kite.cli import _identity_argparse_gettext


def test_identity_translator_installed_and_restored_without_catalog(monkeypatch) -> None:
    monkeypatch.setattr(gettext, "find", lambda *args, **kwargs: None)
    monkeypatch.setattr(argparse, "_", gettext.gettext)

    with _identity_argparse_gettext() as installed:
        assert installed is True
        assert argparse._("positional arguments") == "positional arguments"
    assert argparse._ is gettext.gettext


def test_catalog_present_leaves_argparse_untouched(monkeypatch) -> None:
    monkeypatch.setattr(gettext, "find", lambda *args, **kwargs: ["messages.mo"])
    monkeypatch.setattr(argparse, "_", gettext.gettext)

    with _identity_argparse_gettext() as installed:
        assert installed is False
        assert argparse._ is gettext.gettext


def test_custom_translator_is_not_overwritten(monkeypatch) -> None:
    monkeypatch.setattr(gettext, "find", lambda *args, **kwargs: None)

    def sentinel(message: str) -> str:
        return f"localized:{message}"

    monkeypatch.setattr(argparse, "_", sentinel)

    with _identity_argparse_gettext() as installed:
        assert installed is False
        assert argparse._ is sentinel


def test_late_localization_is_honoured_on_next_call(monkeypatch) -> None:
    monkeypatch.setattr(argparse, "_", gettext.gettext)
    calls = {"catalog": None}

    def find(*args, **kwargs):
        return calls["catalog"]

    monkeypatch.setattr(gettext, "find", find)

    with _identity_argparse_gettext() as first:
        assert first is True
    calls["catalog"] = ["messages.mo"]
    with _identity_argparse_gettext() as second:
        assert second is False


def test_build_parser_restores_argparse_and_keeps_help_identical(monkeypatch) -> None:
    from kite.cli.run import build_parser

    monkeypatch.setattr(argparse, "_", gettext.gettext)
    monkeypatch.setattr(gettext, "find", lambda *args, **kwargs: None)

    fast_text = build_parser().format_help()
    # The decorator must not leave the stdlib patched.
    assert argparse._ is gettext.gettext

    # Compare with the undecorated parser build to prove help text is unchanged.
    baseline_text = build_parser.__wrapped__().format_help()
    assert fast_text == baseline_text
    assert "positional arguments" in fast_text
    assert "options" in fast_text
