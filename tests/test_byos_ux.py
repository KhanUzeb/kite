"""BYOK/BYOS credential UX helpers."""

from __future__ import annotations

from unittest.mock import patch

from kite.providers.auth.base import AuthStatus
from kite.providers.auth.codex import CodexAuthProvider
from kite.providers.catalog import load_catalog
from kite.providers.credentials import provider_needs_login


def test_provider_needs_login_oauth_unlinked(kite_home) -> None:
    spec = load_catalog().get("chatgpt")
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert provider_needs_login(spec) is True


def test_provider_needs_login_oauth_linked(kite_home) -> None:
    spec = load_catalog().get("chatgpt")
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(True, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert provider_needs_login(spec) is False


def test_provider_needs_login_byok_missing(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert provider_needs_login(load_catalog().get("groq")) is True


def test_kite_login_parser_registered() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["login", "chatgpt"])
    assert args.command == "login"
    assert args.provider == "chatgpt"


def test_kite_logout_parser_registered() -> None:
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["logout", "codex"])
    assert args.command == "logout"
    assert args.provider == "codex"
