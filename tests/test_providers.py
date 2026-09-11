"""Credentials, BYOS OAuth, model select, reasoning, Codex LiteLLM auth."""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kite.providers.auth.base import AuthStatus, LoginResult, sanitize_auth_message
from kite.providers.auth.claude import ClaudeCodeAuthProvider
from kite.providers.auth.codex import CodexAuthProvider
from kite.providers.byos import (
    fetch_oauth_model_ids,
    has_oauth_session,
    is_byok_provider,
    login_oauth,
    logout_oauth,
    register_oauth_model_fetcher,
)
from kite.providers.catalog import load_catalog
from kite.providers.credentials import (
    api_key_fingerprint,
    load_kite_env,
    login_provider,
    login_web_tool_key,
    logout_provider,
    logout_web_tool_key,
    mask_api_key_fingerprint,
    prompt_api_key,
    provider_needs_login,
    remove_api_key,
    validate_api_key,
    web_tool_api_key,
    write_api_key,
)
from kite.providers.capabilities import agent_model_warning, model_supports_parallel_tool_calls, model_supports_tools
from kite.providers.resolve import missing_credentials, resolve_model
from kite.providers.select import _can_use_radiolist, _numbered_pick, select_model_interactive


def test_api_key_store_and_validation(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    write_api_key("OPENAI_API_KEY", "new-secret")
    text = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=new-secret" in text and "OTHER=1" in text
    monkeypatch.setenv("GROQ_API_KEY", "abc")
    env.write_text("GROQ_API_KEY=abc\nOTHER=1\n", encoding="utf-8")
    assert remove_api_key("GROQ_API_KEY") is True
    assert "GROQ_API_KEY" not in env.read_text(encoding="utf-8")
    assert validate_api_key("") == "API key cannot be empty"
    assert validate_api_key("valid-key-123") is None
    prompts = iter(["first-key-ok", "second-key-bad"])
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: next(prompts))
    secret, err = prompt_api_key("GROQ_API_KEY", replacing=False)
    assert secret is None and err == "keys did not match — nothing saved"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_abcdefgh")
    assert api_key_fingerprint(load_catalog().get("groq")) == "••••efgh"
    assert mask_api_key_fingerprint("sk-abcdefghijklmnop") == "••••mnop"
    if os.name != "nt":
        write_api_key("GROQ_API_KEY", "secret")
        assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_kite_env_placeholder_and_alias_cleanup(tmp_path, monkeypatch) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / ".env").write_text("GROQ_API_KEY=\n", encoding="utf-8")
    kite_env = tmp_path / "kite" / ".env"
    kite_env.parent.mkdir()
    kite_env.write_text("GROQ_API_KEY=from-kite-home\n", encoding="utf-8")
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: kite_env)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    load_kite_env()
    assert os.getenv("GROQ_API_KEY") == "from-kite-home"
    env = tmp_path / ".env"
    env.write_text("NGC_API_KEY=old-alias\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: "new-primary-key")
    code, _msg, name = login_provider("nvidia", set_default=False, console=None)
    assert code == 0 and name == "nvidia"
    assert "NGC_API_KEY" not in env.read_text(encoding="utf-8")


def test_web_tool_keys_and_cli(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: "tvly-test-key-abcdefgh")
    code, msg, name = login_web_tool_key("tavily", console=None)
    assert code == 0 and name == "tavily" and web_tool_api_key("tavily") == "tvly-test-key-abcdefgh"
    env.write_text("EXA_API_KEY=exa-secret-key\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setenv("EXA_API_KEY", "exa-secret-key")
    out_code, out_msg = logout_web_tool_key("exa")
    assert out_code == 0 and "removed" in out_msg and web_tool_api_key("exa") is None
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: "fc-test-key-abcdefghij")
    code, _msg, name = login_provider("firecrawl", set_default=False, console=None)
    assert code == 0 and web_tool_api_key("firecrawl") == "fc-test-key-abcdefghij"
    from kite.cli.run import build_parser
    from kite.providers.credentials import configured_web_tool_keys

    parser = build_parser()
    assert parser.parse_args(["web-keys", "set", "tavily"]).name == "tavily"
    env.write_text("TAVILY_API_KEY=tvly-abcdefg-xyz\n", encoding="utf-8")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abcdefg-xyz")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    rows = {n: ok for n, ok, _env in configured_web_tool_keys()}
    assert rows["tavily"] is True and rows["exa"] is False


def test_claude_linked_without_key_is_not_usable(monkeypatch, kite_home) -> None:
    from kite.config.readiness import assess_setup_status
    from kite.providers.credentials import configured_providers, inspect_provider_credentials

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec = load_catalog().get("claude")
    auth = MagicMock()
    auth.status.return_value = AuthStatus(True, "Claude Code subscription linked.")
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", lambda *_a, **_k: auth)
    monkeypatch.setattr("kite.providers.resolve.has_oauth_session", lambda *_a, **_k: True)
    status = inspect_provider_credentials(spec)
    assert status.linked is True and status.usable is False
    assert "claude" not in [name for name, ok, _ in configured_providers() if ok]
    msg = missing_credentials(resolve_model(provider="claude"))
    assert msg and "kite keys --set anthropic" in msg and "claude auth login" not in msg
    setup = assess_setup_status(provider="claude")
    assert setup.ready is False
    blob = " ".join(setup.blockers + setup.hints)
    assert "claude auth login" not in blob.lower()


def test_fast_setup_ready_with_key_but_no_saved_model(monkeypatch, kite_home) -> None:
    from kite.config.readiness import assess_setup_status_fast, format_setup_banner
    from kite.config.user import UserConfig

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    cfg = UserConfig()
    status = assess_setup_status_fast(config=cfg)
    assert status.ready is True
    assert format_setup_banner(status) == ""
    claude_default = UserConfig(default_provider="claude")
    still = assess_setup_status_fast(config=claude_default)
    assert still.ready is True
    explicit = assess_setup_status_fast(provider="claude", config=claude_default)
    assert explicit.ready is False


def test_claude_login_mentions_api_key_when_unusable(monkeypatch, kite_home) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("kite.providers.auth.claude.claude_cli_path", lambda: "claude")
    provider = ClaudeCodeAuthProvider()
    states = [AuthStatus(False, "need login"), AuthStatus(True, "Claude Code subscription linked.")]
    monkeypatch.setattr(provider, "status", lambda: states.pop(0) if states else AuthStatus(True, "Claude Code subscription linked."))

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("kite.providers.auth.claude._run_claude_auth", lambda *_a, **_k: _Proc())
    result = provider.login()
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY" in result.message
    assert "kite keys --set anthropic" in result.message


def test_byos_oauth_session_and_login_hints(kite_home: Path) -> None:
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(True, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert has_oauth_session("chatgpt") is True
            assert provider_needs_login(load_catalog().get("chatgpt")) is False
    with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert has_oauth_session("chatgpt") is False
            assert provider_needs_login(load_catalog().get("chatgpt")) is True
    spec = load_catalog().get("chatgpt")
    with patch.object(auth, "logout", return_value=True):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert logout_oauth(spec) is True
    with patch("kite.providers.resolve.has_oauth_session", return_value=False):
        with patch("kite.providers.resolve.subscription_login_hint", side_effect=lambda s: f"Run: kite login {s.name}"):
            msg = missing_credentials(resolve_model(provider="chatgpt"))
            assert msg and "kite login" in msg
    register_oauth_model_fetcher("chatgpt", lambda: ("gpt-5.6-luna", "gpt-5.3-codex"))
    assert fetch_oauth_model_ids(spec, refresh=True) == ("gpt-5.6-luna", "gpt-5.3-codex")
    assert not is_byok_provider(load_catalog().get("chatgpt"))
    assert is_byok_provider(load_catalog().get("anthropic"))
    from kite.cli.run import build_parser
    from kite.providers.credentials import resolve_byos_provider_name

    assert build_parser().parse_args(["login", "chatgpt"]).provider == "chatgpt"
    assert build_parser().parse_args(["logout", "codex"]).provider == "codex"
    assert resolve_byos_provider_name("xai") == "grok"
    grok_auth = MagicMock()
    grok_auth.logout.return_value = True
    with patch("kite.providers.byos.get_auth_provider", return_value=grok_auth):
        code, _msg = logout_provider("xai", byos_aliases=True)
    assert code == 0


def test_oauth_does_not_write_project_env_or_api_keys(kite_home: Path, tmp_path: Path, monkeypatch, caplog) -> None:
    project_env = tmp_path / ".env"
    project_env.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    spec = load_catalog().get("chatgpt")
    auth = CodexAuthProvider()
    with patch.object(auth, "login", return_value=LoginResult(0, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            login_oauth(spec)
    assert project_env.read_text(encoding="utf-8") == "FOO=bar\n"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    claude = ClaudeCodeAuthProvider()
    with patch.object(claude, "login", return_value=LoginResult(0, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=claude):
            login_oauth(load_catalog().get("claude"))
    env_path = kite_home / ".env"
    if env_path.is_file():
        text = env_path.read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" not in text
    cleaned = sanitize_auth_message("failed: access_token=eyJhbGciOiJIUzI1NiJ9.abc.def Bearer sk-ant-oat01-abc")
    assert "eyJ" not in cleaned and "sk-ant-oat" not in cleaned
    secret = "sk-ant-oat01-super-secret-token-value"
    with caplog.at_level(logging.DEBUG):
        sanitize_auth_message(f"error with {secret}")
    assert secret not in caplog.text


def test_select_model_byos_and_windows_picker(kite_home, monkeypatch) -> None:
    monkeypatch.setattr("kite.providers.select.sys.platform", "win32")
    assert _can_use_radiolist() is False
    console = MagicMock()
    console.input.return_value = "2"
    assert _numbered_pick(console, [("a", "alpha"), ("b", "beta"), ("c", "gamma")], current="a", title="t", noun="model") == "b"
    monkeypatch.setattr("kite.providers.select._can_use_radiolist", lambda: False)
    monkeypatch.setattr("kite.providers.byos.has_oauth_session", lambda _p: False)
    code, provider, _model = select_model_interactive(MagicMock(), "chatgpt")
    assert code == 1 and provider is None
    monkeypatch.setattr("kite.providers.byos.has_oauth_session", lambda _p: True)
    monkeypatch.setattr("kite.providers.byos.fetch_oauth_model_ids", lambda spec, refresh=False: ("gpt-5.6-luna", "gpt-5.4"))
    console.input.return_value = "2"
    code, provider, model = select_model_interactive(console, "chatgpt", persist=False)
    assert code == 0 and provider == "chatgpt" and model == "gpt-5.4"


def test_reasoning_levels_and_slash_visibility() -> None:
    from kite.cli.slash import CommandIndex, SlashSpec
    from kite.models.reasoning import ReasoningSupport, apply_reasoning, encode_reasoning, split_reasoning
    from kite.ui.complete import _visible_specs

    info = ReasoningSupport(True, True, True, True, thinking_kwargs={"reasoning_effort": "high"}, fast_kwargs={"reasoning_effort": "low"}, efforts=("none", "low", "medium", "high"))
    assert info.thinking_levels() == ("medium", "high")
    assert split_reasoning("thinking:high") == ("thinking", "high")
    assert encode_reasoning("thinking", "high") == "thinking:high"
    assert apply_reasoning({}, info, "thinking", effort="medium")["reasoning_effort"] == "medium"
    specs = {
        "thinking": SlashSpec("thinking", "control", "builtin", "t"),
        "fast": SlashSpec("fast", "control", "builtin", "f"),
        "reasoning": SlashSpec("reasoning", "control", "builtin", "r"),
    }
    index = CommandIndex(specs=specs)
    names = {s.name for s in _visible_specs(index, support=ReasoningSupport(True, False, True, True))}
    assert "thinking" not in names and "reasoning" not in names


def test_codex_litellm_flattens_and_materializes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.providers.auth import codex_litellm
    from kite.providers.auth.codex import CodexAuthProvider
    from kite.providers.auth.codex_litellm import CodexLitellmAuthError, flatten_codex_auth_record

    nested = {"tokens": {"access_token": "access-abc", "refresh_token": "refresh-xyz", "id_token": "id-123", "account_id": "acct-1"}}
    flat = flatten_codex_auth_record(nested)
    assert flat["access_token"] == "access-abc" and flatten_codex_auth_record({"access_token": "a"})["access_token"] == "a"
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"tokens": {"access_token": "tok", "refresh_token": "ref", "id_token": "idt", "account_id": "acc"}}), encoding="utf-8")
    out = tmp_path / "kite-oauth"
    monkeypatch.setattr(codex_litellm, "_codex_home", lambda: str(codex_home))
    monkeypatch.setattr(codex_litellm, "_kite_chatgpt_token_dir", lambda: out)
    monkeypatch.setattr("kite.providers.auth.codex._codex_home", lambda: str(codex_home))
    token_dir = Path(codex_litellm.materialize_litellm_chatgpt_auth())
    auth = json.loads((token_dir / "auth.json").read_text(encoding="utf-8"))
    assert auth["access_token"] == "tok" and "tokens" not in auth
    env = CodexAuthProvider().litellm_env()
    assert env["CHATGPT_TOKEN_DIR"] == str(out) and env["CHATGPT_TOKEN_DIR"] != str(codex_home)
    (codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt"}), encoding="utf-8")
    with pytest.raises(CodexLitellmAuthError):
        codex_litellm.materialize_litellm_chatgpt_auth()


def test_model_tool_support_is_metadata_driven() -> None:
    assert agent_model_warning("") == "No model selected — agent mode requires a tool-capable chat model."
    assert agent_model_warning("text-embedding-3-small") is not None
    assert agent_model_warning("my-custom-agent-model") is None
    assert agent_model_warning("custom-model", raw={"capabilities": {"tools": False}}) is not None
    assert model_supports_tools(raw={"supported_parameters": ["tools", "tool_choice"]}) is True
    assert model_supports_tools(raw={"capabilities": {"tools": True}}) is True
    from kite.providers.list_models import RemoteModel

    remote = RemoteModel(id="vendor/foo", raw={"supported_parameters": ["tools"]})
    assert remote.supports_tools() is True
    assert model_supports_parallel_tool_calls(raw={"supported_parameters": ["parallel_tool_calls", "tools"]}) is True
    assert model_supports_parallel_tool_calls(raw={"capabilities": {"tools": False}}) is False
