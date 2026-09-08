"""BYOS OAuth subscription provider tests."""

from __future__ import annotations

import json
import logging
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kite.providers.auth.base import AuthStatus, LoginResult, sanitize_auth_message
from kite.providers.auth.claude import ClaudeCodeAuthProvider, claude_auth_status
from kite.providers.auth.codex import CodexAuthProvider, CodexSdkError
from kite.providers.auth.grok import GrokCliAuthProvider
from kite.providers.byos import (
    fetch_oauth_model_ids,
    has_oauth_session,
    is_byok_provider,
    login_oauth,
    logout_oauth,
    oauth_auth_file,
    register_oauth_model_fetcher,
)
from kite.providers.catalog import load_catalog
from kite.providers.credentials import login_provider, logout_provider, write_api_key
from kite.providers.resolve import missing_credentials, resolve_model


def test_has_oauth_session_codex_linked() -> None:
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(True, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert has_oauth_session("chatgpt") is True


def test_has_oauth_session_unlinked() -> None:
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert has_oauth_session("chatgpt") is False


def test_logout_oauth_delegates() -> None:
    spec = load_catalog().get("chatgpt")
    assert spec is not None
    auth = CodexAuthProvider()
    with patch.object(auth, "logout", return_value=True):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert logout_oauth(spec) is True


def test_missing_credentials_suggests_login(kite_home: Path) -> None:
    with patch("kite.providers.byos.has_oauth_session", return_value=False):
        with patch(
            "kite.providers.resolve.subscription_login_hint",
            side_effect=lambda spec: f"Run: kite login {spec.name}",
        ):
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


def test_codex_fetch_models_via_sdk() -> None:
    auth = CodexAuthProvider()
    model = MagicMock()
    model.slug = "gpt-5.6-luna"
    models_resp = MagicMock()
    models_resp.models = [model]
    account_resp = MagicMock()
    account_resp.account = MagicMock(root=object())

    mock_codex = MagicMock()
    mock_codex.__enter__ = MagicMock(return_value=mock_codex)
    mock_codex.__exit__ = MagicMock(return_value=False)
    mock_codex.account.return_value = account_resp
    mock_codex.models.return_value = models_resp

    with patch("kite.providers.auth.codex._open_codex", return_value=mock_codex):
        assert auth.fetch_model_ids() == ("gpt-5.6-luna",)


def test_codex_login_browser() -> None:
    auth = CodexAuthProvider()
    account_after = MagicMock()
    account_after.account = MagicMock(root=object())
    login_handle = MagicMock()
    login_handle.auth_url = "https://auth.openai.com/codex"
    login_handle.wait.return_value = MagicMock(success=True)
    mock_codex = MagicMock()
    mock_codex.__enter__ = MagicMock(return_value=mock_codex)
    mock_codex.__exit__ = MagicMock(return_value=False)
    mock_codex.account.return_value = account_after
    mock_codex.login_chatgpt.return_value = login_handle

    with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
        with patch("kite.providers.auth.codex.require_codex_sdk"):
            with patch("kite.providers.auth.codex._open_codex", return_value=mock_codex):
                result = auth.login(device=False, console=None)
    assert result.exit_code == 0
    assert "linked" in result.message.lower()


def test_codex_login_device() -> None:
    auth = CodexAuthProvider()
    account_after = MagicMock()
    account_after.account = MagicMock(root=object())
    device_handle = MagicMock()
    device_handle.verification_url = "https://auth.openai.com/codex/device"
    device_handle.user_code = "ABCD-1234"
    device_handle.wait.return_value = MagicMock(success=True)
    mock_codex = MagicMock()
    mock_codex.__enter__ = MagicMock(return_value=mock_codex)
    mock_codex.__exit__ = MagicMock(return_value=False)
    mock_codex.account.return_value = account_after
    mock_codex.login_chatgpt_device_code.return_value = device_handle

    with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
        with patch("kite.providers.auth.codex.require_codex_sdk"):
            with patch("kite.providers.auth.codex._open_codex", return_value=mock_codex):
                result = auth.login(device=True, console=None)
    assert result.exit_code == 0


def test_codex_login_already_authenticated() -> None:
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(True, "already")):
        with patch("kite.providers.auth.codex._open_codex") as open_codex:
            result = auth.login()
            open_codex.assert_not_called()
    assert result.exit_code == 0
    assert "already" in result.message.lower()


def test_codex_login_sdk_missing() -> None:
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
        with patch(
            "kite.providers.auth.codex.require_codex_sdk",
            side_effect=CodexSdkError("openai-codex missing"),
        ):
            result = auth.login()
    assert result.exit_code == 2
    assert "openai-codex" in result.message


def test_codex_logout_uses_sdk() -> None:
    auth = CodexAuthProvider()
    account_resp = MagicMock()
    account_resp.account = MagicMock(root=object())
    mock_codex = MagicMock()
    mock_codex.__enter__ = MagicMock(return_value=mock_codex)
    mock_codex.__exit__ = MagicMock(return_value=False)
    mock_codex.account.return_value = account_resp

    with patch("kite.providers.auth.codex._open_codex", return_value=mock_codex):
        assert auth.logout() is True
    mock_codex.logout.assert_called_once()


def test_claude_cli_missing() -> None:
    with patch("kite.providers.auth.claude.claude_cli_path", return_value=None):
        status = claude_auth_status()
    assert status.authenticated is False
    assert "Claude Code CLI" in status.message


def test_claude_auth_status_via_cli() -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = json.dumps({"email": "user@example.com", "authMethod": "subscription"})
    with patch("kite.providers.auth.claude.claude_cli_path", return_value="/bin/claude"):
        with patch("kite.providers.auth.claude._run_claude_auth", return_value=proc):
            status = claude_auth_status()
    assert status.authenticated is True
    assert "user@example.com" in status.account_label


def test_claude_login_delegates_cli() -> None:
    auth = ClaudeCodeAuthProvider()
    proc = MagicMock(returncode=0, stdout="", stderr="")
    with patch("kite.providers.auth.claude.claude_cli_path", return_value="/bin/claude"):
        with patch("kite.providers.auth.claude._run_claude_auth", return_value=proc):
            with patch.object(auth, "status", side_effect=[
                AuthStatus(False, "not linked"),
                AuthStatus(True, "Claude Code subscription linked."),
            ]):
                result = auth.login()
    assert result.exit_code == 0


def test_claude_does_not_read_credentials_file(tmp_path: Path) -> None:
    creds = tmp_path / ".claude" / ".credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-secret", "expiresAt": 9999999999}}),
        encoding="utf-8",
    )
    with patch("kite.providers.auth.claude.claude_cli_path", return_value=None):
        status = claude_auth_status()
    assert status.authenticated is False
    assert "sk-ant-oat" not in status.message


def test_grok_cli_missing() -> None:
    auth = GrokCliAuthProvider()
    with patch("kite.providers.auth.grok.grok_cli_path", return_value=None):
        status = auth.status()
    assert status.authenticated is False
    assert "Grok CLI" in status.message


def test_grok_login_browser(tmp_path: Path) -> None:
    auth = GrokCliAuthProvider()
    auth_file = tmp_path / "auth.json"
    proc = MagicMock(returncode=0, stdout="", stderr="")

    with patch("kite.providers.auth.grok.grok_cli_path", return_value="/bin/grok"):
        with patch("kite.providers.auth.grok.grok_auth_file", return_value=auth_file):
            with patch("kite.providers.auth.grok.run_cli", return_value=proc):
                with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
                    auth_file.write_text('{"ok": true}', encoding="utf-8")
                    result = auth.login(device=False)
    assert result.exit_code == 0


def test_grok_login_device(tmp_path: Path) -> None:
    auth = GrokCliAuthProvider()
    auth_file = tmp_path / "auth.json"
    proc = MagicMock(returncode=0, stdout="", stderr="")

    with patch("kite.providers.auth.grok.grok_cli_path", return_value="/bin/grok"):
        with patch("kite.providers.auth.grok.grok_auth_file", return_value=auth_file):
            with patch("kite.providers.auth.grok.run_cli", return_value=proc) as run_cli:
                with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
                    auth_file.write_text('{"ok": true}', encoding="utf-8")
                    auth.login(device=True)
    run_cli.assert_called_once()
    assert "--device-auth" in run_cli.call_args[0]


def test_grok_logout(tmp_path: Path) -> None:
    auth = GrokCliAuthProvider()
    auth_file = tmp_path / "auth.json"
    auth_file.write_text("{}", encoding="utf-8")
    proc = MagicMock(returncode=0, stdout="", stderr="")
    with patch("kite.providers.auth.grok.grok_cli_path", return_value="/bin/grok"):
        with patch("kite.providers.auth.grok.grok_auth_file", return_value=auth_file):
            with patch("kite.providers.auth.grok.run_cli", return_value=proc):
                assert auth.logout() is True
    assert not auth_file.exists()


def test_oauth_provider_not_byok_selectable() -> None:
    assert not is_byok_provider(load_catalog().get("chatgpt"))
    assert is_byok_provider(load_catalog().get("anthropic"))


def test_sanitize_auth_message_redacts_tokens() -> None:
    raw = "failed: access_token=eyJhbGciOiJIUzI1NiJ9.abc.def Bearer sk-ant-oat01-abc"
    cleaned = sanitize_auth_message(raw)
    assert "eyJ" not in cleaned
    assert "sk-ant-oat" not in cleaned
    assert "access_token=" not in cleaned


def test_tokens_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    secret = "sk-ant-oat01-super-secret-token-value"
    with caplog.at_level(logging.DEBUG):
        sanitize_auth_message(f"error with {secret}")
    assert secret not in caplog.text


def test_auth_exceptions_sanitized() -> None:
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
    msg = sanitize_auth_message(f"OAuth failed: {token}")
    assert token not in msg


def test_project_env_not_modified_with_oauth(kite_home: Path, tmp_path: Path, monkeypatch) -> None:
    project_env = tmp_path / ".env"
    project_env.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    spec = load_catalog().get("chatgpt")
    auth = CodexAuthProvider()
    with patch.object(auth, "login", return_value=LoginResult(0, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            login_oauth(spec)

    assert project_env.read_text(encoding="utf-8") == "FOO=bar\n"
    assert "oauth" not in project_env.read_text(encoding="utf-8").lower()


def test_oauth_not_copied_to_api_key_store(kite_home: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec = load_catalog().get("claude")
    auth = ClaudeCodeAuthProvider()
    with patch.object(auth, "login", return_value=LoginResult(0, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            login_oauth(spec)
    env_path = kite_home / ".env"
    if env_path.is_file():
        text = env_path.read_text(encoding="utf-8")
        assert "sk-ant-oat" not in text
        assert "ANTHROPIC_API_KEY" not in text


def test_kite_env_permissions(kite_home: Path) -> None:
    path = write_api_key("GROQ_API_KEY", "grq-test-key-abcdefghij")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o077 == 0


def test_login_alias_xai_to_grok() -> None:
    from kite.providers.credentials import resolve_byos_provider_name

    assert resolve_byos_provider_name("xai") == "grok"


def test_logout_provider_byos_alias() -> None:
    auth = GrokCliAuthProvider()
    with patch.object(auth, "logout", return_value=True):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            code, msg = logout_provider("xai", byos_aliases=True)
    assert code == 0
