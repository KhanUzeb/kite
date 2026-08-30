"""Maintainer dashboard is gated — not a public command."""

from __future__ import annotations

import argparse

from kite.cli.stats import cmd_maintainer_dashboard, maintainer_enabled


def test_maintainer_disabled_without_key(monkeypatch) -> None:
    monkeypatch.delenv("KITE_MAINTAINER_KEY", raising=False)
    assert maintainer_enabled() is False
    code = cmd_maintainer_dashboard(argparse.Namespace(json=False))
    assert code == 2


def test_maintainer_enabled_with_key(monkeypatch) -> None:
    monkeypatch.setenv("KITE_MAINTAINER_KEY", "my-secret")
    assert maintainer_enabled() is True
