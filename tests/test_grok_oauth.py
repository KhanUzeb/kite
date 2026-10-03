"""Grok CLI auth.json → LiteLLM flat xAI OAuth bridge (no network, no real creds)."""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

import kite.providers.auth.grok_litellm as grok_litellm
from kite.providers.auth.grok_litellm import (
    GrokLitellmAuthError,
    flatten_grok_auth_record,
    litellm_xai_env,
    materialize_litellm_xai_auth,
    xai_subscription_headers,
)

_NESTED_KEY = "https://auth.x.ai::123e4567-e89b-12d3-a456-426614174000"
_ISO_EXPIRY = "2030-01-01T00:00:00Z"


def _nested_payload() -> dict:
    return {
        _NESTED_KEY: {
            "key": "ACC",
            "refresh_token": "REF",
            "expires_at": _ISO_EXPIRY,
        }
    }


def _write_grok_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: dict) -> Path:
    grok_home = tmp_path / "grok_home"
    grok_home.mkdir(exist_ok=True)
    (grok_home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("GROK_HOME", str(grok_home))
    return grok_home


def _offline_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args: object, **_kwargs: object) -> object:
        raise ConnectionError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", _raise)


def _c_test_grok_auth_record_shapes_and_expiry() -> None:
    flat = flatten_grok_auth_record(_nested_payload())
    assert flat["access_token"] == "ACC"
    assert flat["refresh_token"] == "REF"
    assert isinstance(flat["expires_at"], float)
    assert flat["expires_at"] == pytest.approx(
        datetime(2030, 1, 1, tzinfo=UTC).timestamp()
    )
    passthrough = flatten_grok_auth_record(
        {"access_token": "ACC", "refresh_token": "REF", "expires_at": 123.0}
    )
    assert passthrough["access_token"] == "ACC"
    assert passthrough["refresh_token"] == "REF"
    assert passthrough["expires_at"] == 123.0
    assert flatten_grok_auth_record({}) == {}
    assert flatten_grok_auth_record({_NESTED_KEY: {"refresh_token": "REF"}}) == {}
    assert flatten_grok_auth_record({_NESTED_KEY: "not-a-dict"}) == {}
    # Expiry coercion: ISO, numeric, numeric-string pass through as float;
    # garbage and missing expiry are dropped.
    iso = flatten_grok_auth_record({"access_token": "A", "expires_at": _ISO_EXPIRY})
    assert isinstance(iso["expires_at"], float)
    numeric = flatten_grok_auth_record({"access_token": "A", "expires_at": 1700000000})
    assert numeric["expires_at"] == pytest.approx(1700000000.0)
    assert isinstance(numeric["expires_at"], float)
    numeric_str = flatten_grok_auth_record({"access_token": "A", "expires_at": "1700000000"})
    assert numeric_str["expires_at"] == pytest.approx(1700000000.0)
    flat = flatten_grok_auth_record({"access_token": "A", "expires_at": "not-a-date"})
    assert "expires_at" not in flat
    missing = flatten_grok_auth_record({"access_token": "A"})
    assert "expires_at" not in missing


def _c_test_materialize_litellm_xai_auth(
    kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_grok_home(monkeypatch, tmp_path, _nested_payload())
    _offline_discovery(monkeypatch)

    dest = materialize_litellm_xai_auth()

    assert dest.startswith(str(kite_home))
    auth_file = Path(dest) / "auth.json"
    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["access_token"] == "ACC"
    assert payload["refresh_token"] == "REF"
    assert isinstance(payload["expires_at"], float)
    assert "token_endpoint" not in payload

    empty_home = tmp_path / "empty_grok_home"
    empty_home.mkdir()
    monkeypatch.setenv("GROK_HOME", str(empty_home))
    with pytest.raises(GrokLitellmAuthError):
        materialize_litellm_xai_auth()

    _write_grok_home(monkeypatch, tmp_path, _nested_payload())
    _offline_discovery(monkeypatch)
    env = litellm_xai_env()
    assert env["XAI_OAUTH_TOKEN_DIR"].startswith(str(kite_home))
    assert (Path(env["XAI_OAUTH_TOKEN_DIR"]) / "auth.json").is_file()
    assert env["XAI_OAUTH_API_BASE"] == "https://cli-chat-proxy.grok.com/v1"


def _c_test_xai_subscription_headers_fallback_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(grok_litellm, "_grok_version_cache", None)
    monkeypatch.setattr("shutil.which", lambda _bin: None)

    headers = xai_subscription_headers()

    assert isinstance(headers["x-grok-client-version"], str)
    assert headers["x-grok-client-version"] != ""


def _c_test_resolve_model_grok_kwargs_include_oauth_extras(
    kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kite.providers.auth.base import AuthStatus
    from kite.providers.resolve import resolve_model

    _write_grok_home(monkeypatch, tmp_path, _nested_payload())
    _offline_discovery(monkeypatch)
    monkeypatch.setattr(grok_litellm, "_grok_version_cache", None)
    monkeypatch.setattr("shutil.which", lambda _bin: None)

    class _FakeXaiAuth:
        def status(self) -> AuthStatus:
            return AuthStatus(True, "linked", method="subscription")

        def litellm_env(self) -> dict[str, str]:
            return {}

        def litellm_extras(self) -> dict[str, object]:
            return {"use_xai_oauth": True}

    fake = _FakeXaiAuth()
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", lambda _key: fake)

    resolved = resolve_model(provider="grok")

    assert resolved.api_key is None
    kwargs = resolved.litellm_kwargs()
    assert kwargs["use_xai_oauth"] is True
    assert isinstance(kwargs["extra_headers"], dict)
    assert kwargs["extra_headers"]["x-grok-client-version"] != ""


def _c_test_grok_oauth_session_and_interactive_login(
    kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """has_oauth_session covers xai/grok ids; interactive login opens the sign-in URL."""
    import subprocess

    from kite.providers.auth import _PROVIDERS
    from kite.providers.auth.grok import GrokCliAuthProvider
    from kite.providers.byos import has_oauth_session
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import inspect_provider_credentials

    _write_grok_home(monkeypatch, tmp_path, _nested_payload())
    monkeypatch.setattr("kite.providers.auth.grok.grok_cli_path", lambda: "grok")
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", _PROVIDERS.get)

    assert has_oauth_session("xai") is True
    assert has_oauth_session("grok") is True

    status = inspect_provider_credentials(load_catalog().get("grok"))
    assert status.linked is True and status.usable is True
    assert status.detail == "linked"

    grok_home = tmp_path / "grok_home_login"
    grok_home.mkdir()
    monkeypatch.setenv("GROK_HOME", str(grok_home))
    monkeypatch.setattr("kite.providers.auth.grok.grok_cli_path", lambda: "grok")
    monkeypatch.setattr("kite.util.tty.is_interactive_tty", lambda **_k: True)

    opened: list[str] = []
    monkeypatch.setattr(
        "kite.providers.auth.ui.open_browser",
        lambda url: opened.append(url) or True,
    )

    def fake_stream(cmd, *args, timeout=0.0, on_line=None, env=None):
        if on_line is not None:
            on_line("Signing in with Grok...\n")
            on_line(
                "Open this URL to sign in:\n"
                "  https://auth.x.ai/oauth2/authorize?response_type=code&state=abc\n"
            )
            on_line("Waiting for authorization...\n")
        (grok_home / "auth.json").write_text(
            json.dumps({"k": {"key": "ACC"}}), encoding="utf-8"
        )
        return subprocess.CompletedProcess([cmd, *args], 0, "ok", "")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", fake_stream)

    result = GrokCliAuthProvider().login(console=None)

    assert result.exit_code == 0
    assert opened and opened[0].startswith("https://auth.x.ai/")


def _c_test_logout_clears_materialized_xai_oauth(kite_home: Path, monkeypatch) -> None:
    import os

    from kite.providers.byos import clear_materialized_oauth, logout_oauth
    from kite.providers.catalog import load_catalog

    spec = load_catalog().get("grok")
    folder = kite_home / "oauth" / "xai"
    folder.mkdir(parents=True)
    (folder / "auth.json").write_text('{"access_token":"secret-token"}', encoding="utf-8")
    monkeypatch.setenv("XAI_OAUTH_TOKEN_DIR", str(folder))
    monkeypatch.setenv("XAI_OAUTH_API_BASE", "https://cli-chat-proxy.grok.com/v1")
    assert clear_materialized_oauth(spec) is True
    assert not folder.exists()
    assert "XAI_OAUTH_TOKEN_DIR" not in os.environ
    assert "XAI_OAUTH_API_BASE" not in os.environ

    folder.mkdir(parents=True)
    (folder / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XAI_OAUTH_TOKEN_DIR", str(folder))

    class _Auth:
        def logout(self) -> bool:
            return False

    monkeypatch.setattr("kite.providers.byos._auth", lambda _spec: _Auth())
    assert logout_oauth(spec) is True
    assert not (folder / "auth.json").exists()
    assert "XAI_OAUTH_TOKEN_DIR" not in os.environ


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_grok_auth_record_shapes_and_expiry, test_materialize_litellm_xai_auth, test_xai_subscription_headers_fallback_version."""
    _c_test_grok_auth_record_shapes_and_expiry()
    _mp1 = pytest.MonkeyPatch()
    try:
        _t1 = tmp_path / "t0_1"
        _t1.mkdir(parents=True, exist_ok=True)
        _k1 = tmp_path / "k0_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_materialize_litellm_xai_auth(tmp_path=_t1, kite_home=_k1, monkeypatch=_mp1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _c_test_xai_subscription_headers_fallback_version(monkeypatch=_mp2)
    finally:
        _mp2.undo()

def test_batch_01(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_resolve_model_grok_kwargs_include_oauth_extras, test_grok_oauth_session_and_interactive_login, test_logout_clears_materialized_xai_oauth."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _t0 = tmp_path / "t1_0"
        _t0.mkdir(parents=True, exist_ok=True)
        _k0 = tmp_path / "k1_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_resolve_model_grok_kwargs_include_oauth_extras(tmp_path=_t0, kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _t1 = tmp_path / "t1_1"
        _t1.mkdir(parents=True, exist_ok=True)
        _k1 = tmp_path / "k1_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_grok_oauth_session_and_interactive_login(tmp_path=_t1, kite_home=_k1, monkeypatch=_mp1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k1_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_logout_clears_materialized_xai_oauth(kite_home=_k2, monkeypatch=_mp2)
    finally:
        _mp2.undo()

