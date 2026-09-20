"""Setup auto-prompt gating — fresh install vs credentials vs marker."""

from __future__ import annotations

from unittest.mock import MagicMock

from kite.config.onboarding import (
    mark_setup_complete,
    onboarding_marker_path,
    should_auto_prompt_setup,
)
from kite.config.readiness import offer_setup_interactive


def test_fresh_install_may_offer_setup_tty(kite_home, monkeypatch) -> None:
    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    console = MagicMock()
    console.input.return_value = "y"
    assert should_auto_prompt_setup() is True
    assert offer_setup_interactive(console) is True
    console.input.assert_called_once()


def test_after_api_key_no_auto_prompt(kite_home, monkeypatch) -> None:
    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    assert should_auto_prompt_setup() is False
    console = MagicMock()
    assert offer_setup_interactive(console) is False
    console.input.assert_not_called()


def test_after_marker_no_auto_prompt(kite_home, monkeypatch) -> None:
    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    mark_setup_complete()
    assert onboarding_marker_path().is_file()
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    assert should_auto_prompt_setup() is False
    console = MagicMock()
    assert offer_setup_interactive(console) is False


def test_byos_linked_no_auto_prompt(kite_home, monkeypatch) -> None:
    from kite.providers.auth.base import AuthStatus

    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    auth = MagicMock()
    auth.status.return_value = AuthStatus(True, "linked")
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", lambda *_a, **_k: auth)
    monkeypatch.setattr("kite.providers.byos.has_oauth_session", lambda *_a, **_k: True)
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    assert should_auto_prompt_setup() is False


def test_headless_never_offers_setup(kite_home, monkeypatch) -> None:
    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: False)
    assert should_auto_prompt_setup() is True
    console = MagicMock()
    assert offer_setup_interactive(console) is False


def test_kite_skip_setup_env(kite_home, monkeypatch) -> None:
    monkeypatch.setenv("KITE_SKIP_SETUP", "1")
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    console = MagicMock()
    assert offer_setup_interactive(console) is False


def test_write_api_key_sets_marker(kite_home) -> None:
    from kite.providers.credentials import write_api_key

    assert not onboarding_marker_path().is_file()
    write_api_key("GROQ_API_KEY", "gsk-test-not-a-real-key")
    assert onboarding_marker_path().is_file()
    assert should_auto_prompt_setup() is False


def test_manual_setup_wizard_marks_complete(kite_home, monkeypatch) -> None:
    from kite.cli.setup import run_setup_wizard

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    monkeypatch.setattr(
        "kite.cli.setup.select_provider_interactive",
        lambda *_a, **_k: "groq",
    )
    monkeypatch.setattr(
        "kite.cli.setup.connect_interactive",
        lambda *_a, **_k: (0, "groq", "llama-3.3-70b-versatile"),
    )
    console = MagicMock()
    code = run_setup_wizard(console)
    assert code == 0
    assert onboarding_marker_path().is_file()
