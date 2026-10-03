"""GitHub release notification helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kite.cli import release_check as rc


def _c_test_parse_version_order() -> None:
    assert rc._parse_version("0.9.8") > rc._parse_version("0.9.7")
    assert rc._parse_version("1.0.0") > rc._parse_version("0.9.99")


def _c_test_check_for_update_uses_cache(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(rc, "kite_home", lambda: home)
    monkeypatch.setattr(rc, "ensure_home", lambda: home)
    monkeypatch.setattr(
        rc,
        "_fetch_latest_release",
        lambda: {"tag_name": "v99.0.0", "html_url": "https://example.com/r"},
    )

    msg = rc.check_for_update(force=True)
    assert msg is not None
    assert "99.0.0" in msg

    cache = json.loads((home / "release_check.json").read_text(encoding="utf-8"))
    assert cache["latest"] == "99.0.0"

    monkeypatch.setattr(rc, "_fetch_latest_release", lambda: None)
    msg2 = rc.check_for_update(force=False)
    assert msg2 is not None
    assert "99.0.0" in msg2


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_parse_version_order, test_check_for_update_uses_cache."""
    _c_test_parse_version_order()
    _mp1 = pytest.MonkeyPatch()
    try:
        _t1 = tmp_path / "t0_1"
        _t1.mkdir(parents=True, exist_ok=True)
        _c_test_check_for_update_uses_cache(tmp_path=_t1, monkeypatch=_mp1)
    finally:
        _mp1.undo()

