"""Antigravity (`agy` CLI) subscription linkage — no network, no real creds."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kite.providers.auth.antigravity import AntigravityAuthProvider


def _marker(kite_home: Path) -> Path:
    return kite_home / "oauth" / "antigravity" / "status.json"


def test_status_missing_cli_points_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: None)

    status = AntigravityAuthProvider().status()

    assert status.authenticated is False
    assert "antigravity.google" in status.message


def test_status_unlinked_points_to_login(monkeypatch: pytest.MonkeyPatch, kite_home: Path) -> None:
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    assert not _marker(kite_home).exists()

    status = AntigravityAuthProvider().status()

    assert status.authenticated is False
    assert "kite login antigravity" in status.message


def test_status_linked_via_marker(monkeypatch: pytest.MonkeyPatch, kite_home: Path) -> None:
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")

    status = AntigravityAuthProvider().status()

    assert status.authenticated is True


def test_login_opens_streamed_url_headless(
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


def test_login_short_circuits_when_linked(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")

    def _fail(*_a: object, **_k: object) -> object:
        raise AssertionError("must not spawn agy when already linked")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", _fail)

    result = AntigravityAuthProvider().login(console=None)

    assert result.exit_code == 0
    assert "already linked" in result.message


def test_logout_clears_marker(kite_home: Path) -> None:
    auth = AntigravityAuthProvider()
    assert auth.logout() is False
    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")
    assert auth.logout() is True
    assert not marker.exists()


def _use_real_auth_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass conftest's autouse OAuth stub so the real registry resolves."""
    from kite.providers.auth import _PROVIDERS

    monkeypatch.setattr("kite.providers.auth.get_auth_provider", _PROVIDERS.get)
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", _PROVIDERS.get)


def test_registry_and_session_resolution(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kite.providers.auth as auth_mod
    from kite.providers.auth import _PROVIDERS, resolve_login_provider
    from kite.providers.byos import has_oauth_session

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


def test_credentials_need_gemini_key_for_calls(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import inspect_provider_credentials

    _use_real_auth_registry(monkeypatch)
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    spec = load_catalog().get("antigravity")
    assert spec.oauth_provider == "antigravity"

    assert inspect_provider_credentials(spec).usable is False

    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")
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
