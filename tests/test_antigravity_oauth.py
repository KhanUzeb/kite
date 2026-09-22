"""Antigravity (`agy` CLI) subscription linkage — no network, no real creds."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kite.providers.auth.antigravity import AntigravityAuthProvider


def _marker(kite_home: Path) -> Path:
    return kite_home / "oauth" / "antigravity" / "status.json"


def _use_real_auth_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass conftest's autouse OAuth stub so the real registry resolves."""
    from kite.providers.auth import _PROVIDERS

    monkeypatch.setattr("kite.providers.auth.get_auth_provider", _PROVIDERS.get)
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", _PROVIDERS.get)


def test_status_states(monkeypatch: pytest.MonkeyPatch, kite_home: Path) -> None:
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: None)
    missing = AntigravityAuthProvider().status()
    assert missing.authenticated is False
    assert "antigravity.google" in missing.message

    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    assert not _marker(kite_home).exists()
    unlinked = AntigravityAuthProvider().status()
    assert unlinked.authenticated is False
    assert "kite login antigravity" in unlinked.message

    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")
    linked = AntigravityAuthProvider().status()
    assert linked.authenticated is True


def test_login_headless_and_short_circuit(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Headless `kite login antigravity` must surface the sign-in URL."""
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    monkeypatch.setattr("kite.util.tty.is_interactive_tty", lambda **_k: False)

    opened: list[str] = []
    monkeypatch.setattr(
        "kite.providers.auth.ui.open_browser",
        lambda url: opened.append(url) or True,
    )

    def fake_stream(cmd, *args, timeout=0.0, on_line=None, env=None):
        if on_line is not None:
            on_line("Waiting for browser authentication…\n")
            on_line("Visit https://accounts.google.com/o/oauth2/auth?client_id=abc to sign in\n")
        return subprocess.CompletedProcess([cmd, *args], 0, "ok", "")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", fake_stream)

    result = AntigravityAuthProvider().login(console=None)

    assert result.exit_code == 0
    assert opened and opened[0].startswith("https://accounts.google.com/")
    assert _marker(kite_home).is_file()
    assert "GEMINI_API_KEY" in result.message

    # Short-circuit when already linked: must not spawn agy again.
    def _fail(*_a: object, **_k: object) -> object:
        raise AssertionError("must not spawn agy when already linked")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", _fail)
    again = AntigravityAuthProvider().login(console=None)
    assert again.exit_code == 0
    assert "already linked" in again.message


def test_logout_clears_marker(kite_home: Path) -> None:
    auth = AntigravityAuthProvider()
    assert auth.logout() is False
    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")
    assert auth.logout() is True
    assert not marker.exists()


def test_registry_session_and_credentials(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kite.providers.auth as auth_mod
    from kite.providers.auth import _PROVIDERS, resolve_login_provider
    from kite.providers.byos import has_oauth_session
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import inspect_provider_credentials

    _use_real_auth_registry(monkeypatch)
    assert resolve_login_provider("antigravity-sub") == "antigravity"
    # Module-attribute access: `from x import y` would keep the conftest stub.
    assert isinstance(auth_mod.get_auth_provider("antigravity"), AntigravityAuthProvider)
    assert _PROVIDERS["antigravity"].provider_key == "antigravity"

    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    assert has_oauth_session("antigravity") is False
    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")
    assert has_oauth_session("antigravity") is True

    spec = load_catalog().get("antigravity")
    assert spec.oauth_provider == "antigravity"
    fresh_marker = _marker(kite_home)
    fresh_marker.unlink()
    assert inspect_provider_credentials(spec).usable is False

    fresh_marker.parent.mkdir(parents=True, exist_ok=True)
    fresh_marker.write_text(json.dumps({"linked": True}), encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    linked_only = inspect_provider_credentials(spec)
    assert linked_only.linked is True and linked_only.usable is False

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    ready = inspect_provider_credentials(spec)
    assert ready.linked is True and ready.usable is True


def test_fetch_model_ids_fallback() -> None:
    assert AntigravityAuthProvider().fetch_model_ids() == (
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    )
    assert AntigravityAuthProvider().litellm_env() == {}
    assert AntigravityAuthProvider().litellm_extras() == {}
