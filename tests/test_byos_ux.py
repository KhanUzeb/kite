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
