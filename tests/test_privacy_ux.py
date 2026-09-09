"""Privacy settings and summaries."""

from __future__ import annotations

from kite.config.user import UserConfig
from kite.memory.session_policy import persistence_summary, set_persistence_mode


def test_set_persistence_mode_persists(kite_home) -> None:
    mode = set_persistence_mode("disabled")
    assert mode == "disabled"
    assert UserConfig.load().session_persistence == "disabled"
    set_persistence_mode("redacted")
    assert UserConfig.load().session_persistence == "redacted"


def test_set_persistence_mode_rejects_invalid() -> None:
    import pytest

    with pytest.raises(ValueError, match="session persistence"):
        set_persistence_mode("bogus")


def test_persistence_summary_keys() -> None:
    summary = persistence_summary()
    assert summary["session_persistence"] in {"full", "redacted", "disabled"}
    assert "skill_trust" in summary
    assert "child_env" in summary
    assert "subprocess_teardown" in summary
    assert "ssrf" in summary
