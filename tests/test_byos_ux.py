"""BYOK/BYOS credential UX helpers."""

from __future__ import annotations

import json

from kite.providers.catalog import load_catalog
from kite.providers.credentials import (
    provider_credential_status,
    provider_needs_login,
)


def test_provider_credential_status_oauth() -> None:
    assert provider_credential_status(ok=True, env_col="oauth") == "linked"
    assert provider_credential_status(ok=False, env_col="oauth") == "login required"
    assert provider_credential_status(ok=True, env_col="GROQ_API_KEY") == "set"


def test_provider_needs_login_oauth_unlinked(kite_home) -> None:
    spec = load_catalog().get("chatgpt")
    assert provider_needs_login(spec) is True


def test_provider_needs_login_oauth_linked(kite_home) -> None:
    from kite.providers.byos import oauth_auth_file

    spec = load_catalog().get("chatgpt")
    auth = oauth_auth_file("chatgpt")
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text(json.dumps({"access_token": "tok"}), encoding="utf-8")
    assert provider_needs_login(spec) is False


def test_provider_needs_login_byok_missing(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    spec = load_catalog().get("groq")
    assert provider_needs_login(spec) is True


def test_kite_login_parser_registered() -> None:
    from kite.cli.run import build_parser

    parser = build_parser()
    args = parser.parse_args(["login", "chatgpt"])
    assert args.command == "login"
    assert args.provider == "chatgpt"
    assert args.set_default is True
    args2 = parser.parse_args(["login", "groq", "--no-set-default"])
    assert args2.set_default is False


def test_credential_type_labels() -> None:
    from kite.providers.credentials import credential_type_label

    catalog = load_catalog()
    assert credential_type_label(catalog.get("groq")) == "BYOK"
    assert credential_type_label(catalog.get("chatgpt")) == "BYOS"
    assert credential_type_label(catalog.get("ollama")) == "local"


def test_render_credentials_table_rows_includes_type() -> None:
    from kite.ui.credentials import render_credentials_table_rows

    text = render_credentials_table_rows(
        [("groq", False, "GROQ_API_KEY"), ("ollama", True, "local")],
        fingerprints={},
    )
    plain = str(text)
    assert "BYOK" in plain
    assert "local" in plain
    assert "groq" in plain


def test_render_byos_login_panel_shows_code_and_url() -> None:
    from kite.ui.credentials import render_byos_login_panel

    spec = load_catalog().get("chatgpt")
    text = str(
        render_byos_login_panel(
            spec,
            url="https://auth.openai.com/codex/device",
            user_code="ABCD-EFGH",
            browser_opened=True,
        )
    )
    assert "BYOS login" in text
    assert "ABCD-EFGH" in text
    assert "auth.openai.com" in text
    assert "Opened your browser" in text


def test_chatgpt_login_opens_browser_and_shows_code(kite_home, monkeypatch) -> None:
    from kite.providers.byos import _login_chatgpt_oauth

    opened: list[str] = []

    class FakeAuth:
        auth_file = str(kite_home / "oauth" / "chatgpt" / "auth.json")

        def get_access_token(self):
            return "tok"

        def _request_device_code(self):
            return {"device_auth_id": "id", "user_code": "WXYZ-1234", "interval": "5"}

        def _record_device_code_request(self):
            return None

        def _poll_for_authorization_code(self, device):
            assert device["user_code"] == "WXYZ-1234"
            return {"authorization_code": "a", "code_challenge": "b", "code_verifier": "c"}

        def _exchange_code_for_tokens(self, code_data):
            return {"access_token": "tok", "refresh_token": "r"}

        def _build_auth_record(self, tokens):
            return tokens

        def _write_auth_file(self, data):
            return None

    monkeypatch.setattr("kite.providers.byos._chatgpt_authenticator", lambda: FakeAuth())
    monkeypatch.setattr("kite.providers.byos.has_oauth_session", lambda _p: False)
    monkeypatch.setattr("kite.providers.byos._open_browser", lambda url: opened.append(url) or True)
    monkeypatch.setattr("kite.providers.byos._secure", lambda _p: None)

    spec = load_catalog().get("chatgpt")
    code, msg = _login_chatgpt_oauth(spec, console=None)
    assert code == 0
    assert opened
    assert "user_code=WXYZ-1234" in opened[0]
    assert "linked" in msg.lower()


def test_claude_login_accepts_pasted_token(kite_home, monkeypatch) -> None:
    from kite.providers.byos import _login_anthropic_oauth, has_oauth_session

    monkeypatch.setattr("kite.providers.byos._import_claude_cli_credentials", lambda: None)
    monkeypatch.setattr("kite.providers.byos._open_browser", lambda _url: True)
    monkeypatch.setattr("kite.providers.byos._prompt_claude_token", lambda _c: "sk-ant-oat01-pasted")

    spec = load_catalog().get("claude")
    code, msg = _login_anthropic_oauth(spec, console=None)
    assert code == 0
    assert has_oauth_session("anthropic")
    assert "linked" in msg.lower()
