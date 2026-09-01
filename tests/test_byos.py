"""BYOS OAuth subscription provider tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from kite.providers.byos import (
    OAuthSession,
    fetch_oauth_model_ids,
    has_oauth_session,
    is_byok_provider,
    logout_oauth,
    oauth_auth_file,
    register_oauth_model_fetcher,
    subscription_login_hint,
)
from kite.providers.catalog import load_catalog
from kite.providers.credentials import configured_providers
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


def test_catalog_oauth_providers() -> None:
    chatgpt = load_catalog().get("chatgpt")
    claude = load_catalog().get("claude")
    grok = load_catalog().get("grok")
    assert chatgpt is not None and chatgpt.auth_kind == "oauth"
    assert claude is not None and claude.oauth_provider == "anthropic"
    assert grok is not None and grok.oauth_provider == "xai"
    assert chatgpt.default_model == "gpt-5.6-luna"
    assert claude.default_model == "claude-opus-5"
    assert grok.default_model == "grok-4.6"


def test_catalog_byok_defaults() -> None:
    anthropic = load_catalog().get("anthropic")
    xai = load_catalog().get("xai")
    assert anthropic is not None
    assert xai is not None
    assert anthropic.default_model == "claude-opus-5"
    assert xai.default_model == "grok-4.6"
    assert is_byok_provider(anthropic)
    assert not is_byok_provider(load_catalog().get("chatgpt"))


def test_missing_credentials_suggests_login(kite_home: Path) -> None:
    for provider in ("chatgpt", "claude", "grok"):
        resolved = resolve_model(provider=provider)
        msg = missing_credentials(resolved)
        assert msg is not None
        assert f"kite login {provider}" in msg or "kite login claude" in msg


def test_subscription_login_hint() -> None:
    spec = load_catalog().get("grok")
    assert spec is not None
    hint = subscription_login_hint(spec)
    assert "kite login grok" in hint


def test_configured_providers_shows_oauth(kite_home: Path) -> None:
    rows = configured_providers()
    chatgpt = next(r for r in rows if r[0] == "chatgpt")
    assert chatgpt[1] is False
    assert chatgpt[2] == "oauth"


def test_fetch_oauth_model_ids_dynamic(kite_home: Path) -> None:
    spec = load_catalog().get("chatgpt")
    assert spec is not None
    register_oauth_model_fetcher("chatgpt", lambda: ("gpt-5.6-luna", "gpt-5.3-codex"))
    ids = fetch_oauth_model_ids(spec, refresh=True)
    assert ids == ("gpt-5.6-luna", "gpt-5.3-codex")


@patch("kite.providers.byos.urllib.request.urlopen")
@patch("kite.providers.byos.oauth_session")
def test_fetch_chatgpt_models_from_api(mock_session, mock_urlopen, kite_home: Path) -> None:
    mock_session.return_value = OAuthSession(access_token="tok", account_id="acct-1")

    class FakeResp:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "models": [
                        {"slug": "gpt-5.6-luna", "display_name": "GPT-5.6 Luna"},
                        {"slug": "gpt-5.3-codex", "display_name": "Codex"},
                    ]
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    mock_urlopen.return_value = FakeResp()

    from kite.providers.byos import _fetch_chatgpt_models_live

    ids = _fetch_chatgpt_models_live()
    assert ids == ("gpt-5.6-luna", "gpt-5.3-codex")


def test_import_claude_credentials(kite_home: Path, monkeypatch, tmp_path: Path) -> None:
    from kite.providers.byos import _import_claude_cli_credentials, _login_anthropic_oauth

    creds = tmp_path / ".claude" / ".credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "sk-ant-oat01-test",
                    "refreshToken": "sk-ant-ort01-test",
                    "expiresAt": 9999999999,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("kite.providers.byos._claude_credentials_path", lambda: creds)
    imported = _import_claude_cli_credentials()
    assert imported is not None
    assert imported["access_token"] == "sk-ant-oat01-test"
    code, msg = _login_anthropic_oauth()
    assert code == 0
    assert has_oauth_session("anthropic")


def test_oauth_provider_not_byok_selectable() -> None:
    assert not is_byok_provider(load_catalog().get("chatgpt"))
    assert not is_byok_provider(load_catalog().get("claude"))
    assert is_byok_provider(load_catalog().get("anthropic"))
