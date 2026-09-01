"""Dashboard CLI smoke test."""

from __future__ import annotations

import argparse

from kite.cli.dashboard import cmd_dashboard


def test_dashboard_json_empty(kite_home, capsys) -> None:
    args = argparse.Namespace(session=None, limit=10, watch=0, json=True)
    code = cmd_dashboard(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "session_count" in (captured.out + captured.err)
