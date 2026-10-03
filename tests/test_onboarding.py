"""Setup auto-prompt gating — fresh install vs credentials vs marker."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kite.config.onboarding import (
    mark_setup_complete,
    onboarding_marker_path,
    should_auto_prompt_setup,
)
from kite.config.readiness import offer_setup_interactive


def _c_test_auto_prompt_gating_fresh_headless_and_skip(kite_home, monkeypatch) -> None:
    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    monkeypatch.setattr("kite.config.onboarding.any_provider_connection", lambda: False)
    monkeypatch.setattr("kite.config.onboarding.onboarding_marker_exists", lambda: False)
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    console = MagicMock()
    console.input.return_value = "y"
    assert should_auto_prompt_setup() is True
    assert offer_setup_interactive(console) is True
    console.input.assert_called_once()

    # Headless terminals never offer setup even when a prompt is due.
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: False)
    assert should_auto_prompt_setup() is True
    assert offer_setup_interactive(MagicMock()) is False

    # Explicit opt-out always wins.
    monkeypatch.setenv("KITE_SKIP_SETUP", "1")
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    assert offer_setup_interactive(MagicMock()) is False


def _c_test_no_prompt_after_connection_marker_or_byos(kite_home, monkeypatch) -> None:
    from kite.providers.auth.base import AuthStatus

    # API key present: no prompt.
    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    assert should_auto_prompt_setup() is False
    console = MagicMock()
    assert offer_setup_interactive(console) is False
    console.input.assert_not_called()

    # Marker present: no prompt.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    mark_setup_complete()
    assert onboarding_marker_path().is_file()
    assert should_auto_prompt_setup() is False
    assert offer_setup_interactive(MagicMock()) is False

    # Linked BYOS session: no prompt (isolated from the marker above).
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    marker = onboarding_marker_path()
    if marker.is_file():
        marker.unlink()
    auth = MagicMock()
    auth.status.return_value = AuthStatus(True, "linked")
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", lambda *_a, **_k: auth)
    monkeypatch.setattr("kite.providers.byos.has_oauth_session", lambda *_a, **_k: True)
    assert should_auto_prompt_setup() is False


def _c_test_key_write_and_wizard_mark_complete(kite_home, monkeypatch) -> None:
    from kite.cli.setup import run_setup_wizard
    from kite.providers.credentials import write_api_key

    assert not onboarding_marker_path().is_file()
    write_api_key("GROQ_API_KEY", "gsk-test-not-a-real-key")
    assert onboarding_marker_path().is_file()
    assert should_auto_prompt_setup() is False

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setattr(
        "kite.cli.setup.select_provider_interactive",
        lambda *_a, **_k: "groq",
    )
    monkeypatch.setattr(
        "kite.cli.setup.connect_interactive",
        lambda *_a, **_k: (0, "groq", "llama-3.3-70b-versatile"),
    )
    assert run_setup_wizard(MagicMock()) == 0
    assert onboarding_marker_path().is_file()


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_auto_prompt_gating_fresh_headless_and_skip, test_no_prompt_after_connection_marker_or_byos, test_key_write_and_wizard_mark_complete."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k0_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_auto_prompt_gating_fresh_headless_and_skip(kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k0_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_no_prompt_after_connection_marker_or_byos(kite_home=_k1, monkeypatch=_mp1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k0_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_key_write_and_wizard_mark_complete(kite_home=_k2, monkeypatch=_mp2)
    finally:
        _mp2.undo()

