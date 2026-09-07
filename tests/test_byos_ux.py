"""BYOK/BYOS credential UX helpers."""

from __future__ import annotations

import json

from kite.providers.catalog import load_catalog
from kite.providers.credentials import provider_needs_login


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
    assert provider_needs_login(load_catalog().get("groq")) is True


def test_kite_login_parser_registered() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["login", "chatgpt"])
    assert args.command == "login"
    assert args.provider == "chatgpt"
