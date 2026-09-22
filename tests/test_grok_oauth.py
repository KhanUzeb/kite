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
    grok_home.mkdir()
    (grok_home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("GROK_HOME", str(grok_home))
    return grok_home


def _offline_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args: object, **_kwargs: object) -> object:
        raise ConnectionError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", _raise)


def test_flatten_nested_grok_cli_shape() -> None:
    flat = flatten_grok_auth_record(_nested_payload())
    assert flat["access_token"] == "ACC"
    assert flat["refresh_token"] == "REF"
    assert isinstance(flat["expires_at"], float)
    assert flat["expires_at"] == pytest.approx(
        datetime(2030, 1, 1, tzinfo=UTC).timestamp()
    )


def test_flatten_already_flat_passes_through() -> None:
    flat = flatten_grok_auth_record(
        {"access_token": "ACC", "refresh_token": "REF", "expires_at": 123.0}
    )
    assert flat["access_token"] == "ACC"
    assert flat["refresh_token"] == "REF"
    assert flat["expires_at"] == 123.0


def test_flatten_empty_or_keyless_returns_empty() -> None:
    assert flatten_grok_auth_record({}) == {}
    assert flatten_grok_auth_record({_NESTED_KEY: {"refresh_token": "REF"}}) == {}
    assert flatten_grok_auth_record({_NESTED_KEY: "not-a-dict"}) == {}


def test_epoch_conversion_accepts_iso_and_numeric() -> None:
    iso = flatten_grok_auth_record({"access_token": "A", "expires_at": _ISO_EXPIRY})
    assert isinstance(iso["expires_at"], float)
    numeric = flatten_grok_auth_record({"access_token": "A", "expires_at": 1700000000})
    assert numeric["expires_at"] == pytest.approx(1700000000.0)
    assert isinstance(numeric["expires_at"], float)
    numeric_str = flatten_grok_auth_record({"access_token": "A", "expires_at": "1700000000"})
    assert numeric_str["expires_at"] == pytest.approx(1700000000.0)


def test_epoch_conversion_garbage_omits_key() -> None:
    flat = flatten_grok_auth_record({"access_token": "A", "expires_at": "not-a-date"})
    assert "expires_at" not in flat
    missing = flatten_grok_auth_record({"access_token": "A"})
    assert "expires_at" not in missing


def test_materialize_offline_discovery_omits_token_endpoint(
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


def test_materialize_missing_auth_file_raises(
    kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_home = tmp_path / "empty_grok_home"
    empty_home.mkdir()
    monkeypatch.setenv("GROK_HOME", str(empty_home))

    with pytest.raises(GrokLitellmAuthError):
        materialize_litellm_xai_auth()


def test_litellm_xai_env_points_at_kite_home(
    kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_grok_home(monkeypatch, tmp_path, _nested_payload())
    _offline_discovery(monkeypatch)

    env = litellm_xai_env()

    assert env["XAI_OAUTH_TOKEN_DIR"].startswith(str(kite_home))
    assert (Path(env["XAI_OAUTH_TOKEN_DIR"]) / "auth.json").is_file()
    assert env["XAI_OAUTH_API_BASE"] == "https://cli-chat-proxy.grok.com/v1"


def test_xai_subscription_headers_fallback_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(grok_litellm, "_grok_version_cache", None)
    monkeypatch.setattr("shutil.which", lambda _bin: None)

    headers = xai_subscription_headers()

    assert isinstance(headers["x-grok-client-version"], str)
    assert headers["x-grok-client-version"] != ""


def test_resolve_model_grok_kwargs_include_oauth_extras(
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


def test_oauth_session_resolves_grok_by_oauth_id_and_catalog_name(
    kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """has_oauth_session must find GrokCliAuthProvider for both 'xai' and 'grok'.

    LOGIN_ALIASES maps xai→grok (a catalog name) while the auth registry is
    keyed by oauth_provider id 'xai'. Misresolving made a linked Grok CLI
    look logged out (`kite login grok` contradicted itself; `kite keys`
    showed login required).
    """
    from kite.providers.auth import _PROVIDERS
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


def test_grok_login_opens_browser_with_streamed_url(
    kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interactive `kite login grok` must open the sign-in URL, not hide it."""
    import subprocess

    from kite.providers.auth.grok import GrokCliAuthProvider

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


def test_logout_clears_materialized_xai_oauth(kite_home: Path, monkeypatch) -> None:
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
