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


@pytest.fixture(autouse=True)
def _isolate_credentials(kite_home, tmp_path, monkeypatch):
    from kite.providers.catalog import load_catalog
    from kite.providers.keys import api_key_env_names

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("kite.providers.credentials._ENV_LOADED_KEY", None)
    for spec in load_catalog().list():
        for name in api_key_env_names(spec):
            monkeypatch.delenv(name, raising=False)


def test_auto_prompt_gating_fresh_headless_and_skip(kite_home, monkeypatch) -> None:
    monkeypatch.delenv("KITE_SKIP_SETUP", raising=False)
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    console = MagicMock()
    console.input.return_value = "y"
    assert should_auto_prompt_setup() is True
    assert offer_setup_interactive(console) is True
    console.input.assert_called_once()
    console.input.return_value = "n"
    assert offer_setup_interactive(console) is False

    # Headless terminals never offer setup even when a prompt is due.
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: False)
    assert should_auto_prompt_setup() is True
    headless = MagicMock()
    assert offer_setup_interactive(headless) is False
    headless.input.assert_not_called()

    # Explicit opt-out always wins.
    monkeypatch.setenv("KITE_SKIP_SETUP", "1")
    monkeypatch.setattr("kite.config.readiness.is_interactive_tty", lambda: True)
    skipped = MagicMock()
    assert offer_setup_interactive(skipped) is False
    skipped.input.assert_not_called()


def test_no_prompt_after_connection_marker_or_byos(kite_home, monkeypatch) -> None:
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
    assert should_auto_prompt_setup() is True
    mark_setup_complete()
    assert onboarding_marker_path().is_file()
    assert should_auto_prompt_setup() is False
    assert offer_setup_interactive(MagicMock()) is False

    # Linked BYOS session: no prompt (isolated from the marker above).
    onboarding_marker_path().unlink()
    assert should_auto_prompt_setup() is True
    monkeypatch.setattr("kite.providers.byos.has_oauth_session", lambda *_a, **_k: True)
    assert should_auto_prompt_setup() is False


def test_key_write_marks_setup_complete(kite_home) -> None:
    from kite.providers.credentials import write_api_key

    assert not onboarding_marker_path().is_file()
    write_api_key("GROQ_API_KEY", "gsk-test-not-a-real-key")
    assert onboarding_marker_path().is_file()
    assert should_auto_prompt_setup() is False


def test_wizard_marks_setup_complete_only_after_connection(kite_home, monkeypatch) -> None:
    from kite.cli.setup import run_setup_wizard
    from kite.config import UserConfig

    model = "llama-3.3-70b-versatile"
    UserConfig(default_provider="groq", default_model=model).save()
    assert not onboarding_marker_path().exists()

    def connect(*_args, **_kwargs):
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
        return 0, "groq", model

    monkeypatch.setattr(
        "kite.cli.setup.select_provider_interactive",
        lambda *_a, **_k: "groq",
    )
    monkeypatch.setattr(
        "kite.cli.setup.connect_interactive",
        lambda *_a, **_k: (130, None, None),
    )
    assert run_setup_wizard(MagicMock()) == 130
    assert not onboarding_marker_path().exists()
    monkeypatch.setattr("kite.cli.setup.connect_interactive", connect)
    assert run_setup_wizard(MagicMock()) == 0
    assert onboarding_marker_path().is_file()

