"""BYOS OAuth subscription provider tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from kite.providers.byos import (
    fetch_oauth_model_ids,
    has_oauth_session,
    is_byok_provider,
    logout_oauth,
    oauth_auth_file,
    register_oauth_model_fetcher,
)
from kite.providers.catalog import load_catalog
from kite.providers.resolve import missing_credentials, resolve_model


def test_oauth_session_detected(kite_home: Path) -> None:
    assert not has_oauth_session("chatgpt")
    auth = oauth_auth_file("chatgpt")
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text(json.dumps({"access_token": "t", "account_id": "acct"}), encoding="utf-8")
    assert has_oauth_session("chatgpt")


def test_logout_oauth(kite_home: Path) -> None:
    spec = load_catalog().get("chatgpt")
    assert spec is not None
    auth = oauth_auth_file("chatgpt")
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text("{}", encoding="utf-8")
    logout_oauth(spec)
    assert not auth.exists()


def test_missing_credentials_suggests_login(kite_home: Path) -> None:
    for provider in ("chatgpt", "claude", "grok"):
        resolved = resolve_model(provider=provider)
        msg = missing_credentials(resolved)
        assert msg is not None
        assert "kite login" in msg


def test_fetch_oauth_model_ids_dynamic(kite_home: Path) -> None:
    spec = load_catalog().get("chatgpt")
    assert spec is not None
    register_oauth_model_fetcher("chatgpt", lambda: ("gpt-5.6-luna", "gpt-5.3-codex"))
    ids = fetch_oauth_model_ids(spec, refresh=True)
    assert ids == ("gpt-5.6-luna", "gpt-5.3-codex")


@patch("kite.providers.byos.urllib.request.urlopen")
@patch("kite.providers.byos.oauth_session")
def test_fetch_chatgpt_models_from_api(mock_session, mock_urlopen, kite_home: Path) -> None:
    mock_session.return_value = type("S", (), {"access_token": "tok", "account_id": "acct-1"})()

    class FakeResp:
        def read(self) -> bytes:
            return json.dumps(
                {"models": [{"slug": "gpt-5.6-luna"}, {"slug": "gpt-5.3-codex"}]}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    mock_urlopen.return_value = FakeResp()
    from kite.providers.byos import _fetch_chatgpt_models_live

    assert _fetch_chatgpt_models_live() == ("gpt-5.6-luna", "gpt-5.3-codex")


def test_import_claude_credentials(kite_home: Path, monkeypatch, tmp_path: Path) -> None:
    from kite.providers.byos import _import_claude_cli_credentials, _login_anthropic_oauth

    creds = tmp_path / ".claude" / ".credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-test", "expiresAt": 9999999999}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("kite.providers.byos._claude_credentials_path", lambda: creds)
    imported = _import_claude_cli_credentials()
    assert imported is not None
    code, _msg = _login_anthropic_oauth(load_catalog().get("claude"), console=None)
    assert code == 0
    assert has_oauth_session("anthropic")


def test_oauth_provider_not_byok_selectable() -> None:
    assert not is_byok_provider(load_catalog().get("chatgpt"))
    assert is_byok_provider(load_catalog().get("anthropic"))
