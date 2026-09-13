"""GitHub release notification helper."""

from __future__ import annotations

import json
from pathlib import Path

from kite.cli import release_check as rc


def test_parse_version_order() -> None:
    assert rc._parse_version("0.9.8") > rc._parse_version("0.9.7")
    assert rc._parse_version("1.0.0") > rc._parse_version("0.9.99")


def test_check_for_update_uses_cache(tmp_path: Path, monkeypatch) -> None:
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
