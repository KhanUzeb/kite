"""Antigravity (`agy` CLI) subscription linkage — no network, no real creds."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kite.providers.auth.antigravity import AntigravityAuthProvider, _auth_url_in_line


def _marker(kite_home: Path) -> Path:
    return kite_home / "oauth" / "antigravity" / "status.json"


def _use_real_auth_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass conftest's autouse OAuth stub so the real registry resolves."""
    from kite.providers.auth import _PROVIDERS

    monkeypatch.setattr("kite.providers.auth.get_auth_provider", _PROVIDERS.get)
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", _PROVIDERS.get)


def _fresh_marker(kite_home: Path) -> None:
    import time

    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"linked": True, "verified_at": time.time(), "verified_via": "agy models"}),
        encoding="utf-8",
    )


def test_auth_url_filter() -> None:
    assert _auth_url_in_line("Visit https://accounts.google.com/o/oauth2/auth?x=1 now") != ""
    assert _auth_url_in_line("see https://antigravity.google/docs/cli/install/") != ""
    assert _auth_url_in_line("callback http://localhost:8080/?code=abc") == ""  # http only
    assert _auth_url_in_line("read https://example.com/docs/update-notes") == ""
    assert _auth_url_in_line("no url here") == ""


def test_status_states(monkeypatch: pytest.MonkeyPatch, kite_home: Path) -> None:
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: None)
    missing = AntigravityAuthProvider().status()
    assert missing.authenticated is False
    assert "antigravity.google" in missing.message

    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    calls: list[str] = []
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session",
        lambda **_k: (calls.append("probe") or (False, ())),
    )
    assert not _marker(kite_home).exists()
    unlinked = AntigravityAuthProvider().status()
    assert unlinked.authenticated is False
    assert "kite login antigravity" in unlinked.message
    assert calls == ["probe"]

    # Fresh verified marker: fast path, no subprocess probe.
    calls.clear()
    _fresh_marker(kite_home)
    linked = AntigravityAuthProvider().status()
    assert linked.authenticated is True
    assert calls == []

    # Stale marker + failed probe: session is gone, marker is cleared.
    stale = _marker(kite_home)
    stale.write_text(json.dumps({"linked": True, "verified_at": 0.0}), encoding="utf-8")
    gone = AntigravityAuthProvider().status()
    assert gone.authenticated is False
    assert not stale.exists()

    # Live probe success marks linked.
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session",
        lambda **_k: (True, ("gemini-3.8-flash-medium",)),
    )
    verified = AntigravityAuthProvider().status()
    assert verified.authenticated is True
    assert _marker(kite_home).is_file()


def test_login_headless_verifies_probe(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Headless login surfaces the sign-in URL and marks linked only on probe success."""
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    monkeypatch.setattr("kite.util.tty.is_interactive_tty", lambda **_k: False)
    # Probe fails before sign-in (status short-circuit skipped), succeeds after.
    probe_calls: list[str] = []

    def fake_probe(**_k):
        probe_calls.append("probe")
        if len(probe_calls) == 1:
            return False, ()
        return True, ("gemini-3.8-flash-medium", "claude-sonnet-4-6")

    monkeypatch.setattr("kite.providers.auth.antigravity.probe_session", fake_probe)

    opened: list[str] = []
    monkeypatch.setattr(
        "kite.providers.auth.ui.open_browser",
        lambda url: opened.append(url) or True,
    )

    def fake_stream(cmd, *args, timeout=0.0, on_line=None, env=None):
        if on_line is not None:
            on_line("Some telemetry: https://example.com/docs\n")
            on_line("Visit https://accounts.google.com/o/oauth2/auth?client_id=abc to sign in\n")
        return subprocess.CompletedProcess([cmd, *args], 0, "ok", "")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", fake_stream)

    result = AntigravityAuthProvider().login(console=None)

    assert result.exit_code == 0
    # Only the auth URL is surfaced — never docs/telemetry links.
    assert opened and opened[0].startswith("https://accounts.google.com/")
    assert all("example.com" not in url for url in opened)
    marker = _marker(kite_home)
    assert marker.is_file()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["linked"] is True and payload["verified_via"] == "agy models"
    assert "GEMINI_API_KEY" in result.message

    # Short-circuit when freshly verified: must not spawn agy again.
    def _fail(*_a: object, **_k: object) -> object:
        raise AssertionError("must not spawn agy when already linked")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", _fail)
    monkeypatch.setattr("kite.providers.auth.antigravity.probe_session", _fail)
    again = AntigravityAuthProvider().login(console=None)
    assert again.exit_code == 0
    assert "already linked" in again.message


def test_login_exit_zero_without_session_fails(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quitting agy (exit 0) without signing in must NOT mark linked."""
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    monkeypatch.setattr("kite.util.tty.is_interactive_tty", lambda **_k: False)
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (False, ())
    )
    monkeypatch.setattr(
        "kite.providers.auth.cli.run_cli_streaming",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "bye", ""),
    )
    result = AntigravityAuthProvider().login(console=None)
    assert result.exit_code == 2
    assert "did not complete" in result.message
    assert not _marker(kite_home).exists()


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
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (False, ())
    )
    assert has_oauth_session("antigravity") is False
    _fresh_marker(kite_home)
    # Status verdicts are cached — a marker transition invalidates
    # (login_oauth/logout_oauth do this in production).
    from kite.providers.byos import invalidate_auth_status_cache

    invalidate_auth_status_cache("antigravity")
    assert has_oauth_session("antigravity") is True

    spec = load_catalog().get("antigravity")
    assert spec.oauth_provider == "antigravity"
    fresh_marker = _marker(kite_home)
    fresh_marker.unlink()
    assert inspect_provider_credentials(spec).usable is False

    _fresh_marker(kite_home)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    linked_only = inspect_provider_credentials(spec)
    assert linked_only.linked is True and linked_only.usable is False

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    ready = inspect_provider_credentials(spec)
    assert ready.linked is True and ready.usable is True


def test_fetch_model_ids_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (False, ())
    )
    assert AntigravityAuthProvider().fetch_model_ids() == (
        "gemini-3.8-flash-medium",
        "gemini-3.7-flash-medium",
        "gemini-3.1-pro-high",
        "claude-sonnet-4-6",
    )
    assert AntigravityAuthProvider().litellm_env() == {}
    assert AntigravityAuthProvider().litellm_extras() == {}


def test_fetch_model_ids_live(kite_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live = ("gemini-3.8-flash-medium", "claude-sonnet-4-6")
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (True, live)
    )
    assert AntigravityAuthProvider().fetch_model_ids() == live
