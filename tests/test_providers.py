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
    has_oauth_session,
    login_oauth,
    logout_oauth,
)
from kite.providers.capabilities import agent_model_warning, model_supports_parallel_tool_calls, model_supports_tools
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
from kite.providers.keys import api_key_env_names, api_key_for
from kite.providers.resolve import missing_credentials, resolve_model
from kite.providers.select import _can_use_radiolist, _numbered_pick, select_model_interactive


@pytest.fixture(autouse=True)
def _isolated_provider_state(monkeypatch, kite_home, workspace, tmp_path):
    from kite.providers import byos, capabilities, credentials

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for cache in ("_auth_status_cache", "_oauth_model_cache", "_OAUTH_MODEL_FETCHERS"):
        monkeypatch.setattr(byos, cache, {})
    monkeypatch.setattr(credentials, "_ENV_LOADED_KEY", None)
    monkeypatch.setattr(capabilities, "_litellm_openai_params", lambda *_a, **_k: None)
    names = {
        name for spec in load_catalog().list() for name in api_key_env_names(spec)
    }
    names.update(("TAVILY_API_KEY", "EXA_API_KEY", "FIRECRAWL_API_KEY", "TINYFISH_API_KEY", "CONTEXT7_API_KEY", "CODEX_HOME", "GROK_HOME", "OTHER", "FOO"))
    names.update(name for values in byos._MATERIALIZED_OAUTH_ENV.values() for name in values)
    for name in names:
        # Register restoration even if production code adds a previously absent key.
        monkeypatch.setenv(name, "")


def test_chatgpt_subscription_serializes_tool_calls_even_when_litellm_advertises_parallel(monkeypatch) -> None:
    monkeypatch.setattr(
        "kite.providers.capabilities._litellm_openai_params",
        lambda *_args, **_kwargs: frozenset({"tools", "parallel_tool_calls"}),
    )
    assert not model_supports_parallel_tool_calls(
        provider="chatgpt", model="gpt-5.6-luna", litellm_model="chatgpt/gpt-5.6-luna"
    )


def test_api_key_storage_and_env_precedence(tmp_path, workspace, kite_home, monkeypatch) -> None:
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
    (workspace / ".env").write_text("GROQ_API_KEY=\n", encoding="utf-8")
    kite_env = kite_home / ".env"
    kite_env.write_text("GROQ_API_KEY=from-kite-home\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: kite_env)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    load_kite_env()
    assert os.getenv("GROQ_API_KEY") == "from-kite-home"
    (workspace / ".env").write_text("GROQ_API_KEY=from-project\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY")
    load_kite_env()
    assert os.getenv("GROQ_API_KEY") == "from-project"
    env2 = tmp_path / ".env2"
    env2.write_text("NGC_API_KEY=old-alias\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env2)
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: "new-primary-key")
    code, _msg, name = login_provider("nvidia", set_default=False, console=None)
    assert code == 0 and name == "nvidia"
    assert "NGC_API_KEY" not in env2.read_text(encoding="utf-8")


def test_web_tool_key_login_logout(tmp_path, monkeypatch) -> None:
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
    from kite.providers.credentials import configured_web_tool_keys

    env.write_text("TAVILY_API_KEY=tvly-abcdefg-xyz\n", encoding="utf-8")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abcdefg-xyz")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    rows = {n: ok for n, ok, _env in configured_web_tool_keys()}
    assert rows["tavily"] is True and rows["exa"] is False


def test_claude_link_and_login_require_api_key(monkeypatch, kite_home) -> None:
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


def test_fast_setup_ready_with_key_but_no_saved_model(monkeypatch, kite_home, tmp_path) -> None:
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
    from kite.config.readiness import is_first_run

    assert is_first_run(explicit) is False
    assert format_setup_banner(explicit) == ""


def test_byos_oauth_login_and_secret_hygiene(kite_home: Path, tmp_path: Path, monkeypatch, caplog) -> None:
    auth = CodexAuthProvider()
    with patch.object(auth, "status", return_value=AuthStatus(True, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert has_oauth_session("chatgpt") is True
            assert provider_needs_login(load_catalog().get("chatgpt")) is False
    # Status verdicts are cached (slow CLI/SDK probes); a transition must
    # invalidate explicitly — exactly what login_oauth/logout_oauth do.
    from kite.providers.byos import invalidate_auth_status_cache

    invalidate_auth_status_cache("chatgpt")
    with patch.object(auth, "status", return_value=AuthStatus(False, "not linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert has_oauth_session("chatgpt") is False
            assert provider_needs_login(load_catalog().get("chatgpt")) is True
    spec = load_catalog().get("chatgpt")
    with patch.object(auth, "logout", return_value=True):
        with patch("kite.providers.byos.get_auth_provider", return_value=auth):
            assert logout_oauth(spec) is True
    from kite.providers.credentials import resolve_byos_provider_name

    assert resolve_byos_provider_name("xai") == "grok"
    grok_auth = MagicMock()
    grok_auth.logout.return_value = True
    with patch("kite.providers.byos.get_auth_provider", return_value=grok_auth):
        code, _msg = logout_provider("xai", byos_aliases=True)
    assert code == 0
    # Headless/device ChatGPT login must still open the verification URL.
    device_auth = CodexAuthProvider()
    linked = {"ok": False}

    class _Root:
        email = "user@example.com"

    class _Account:
        root = _Root()

    class _Resp:
        account = _Account()

    class _Login:
        verification_url = "https://chatgpt.com/codex/devices?user_code=ABCD-1234"
        user_code = "ABCD-1234"
        auth_url = "https://auth.openai.com/oauth/authorize?x=1"

        def wait(self):
            linked["ok"] = True
            return MagicMock(success=True)

    class _Codex:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def account(self):
            return _Resp() if linked["ok"] else None

        def login_chatgpt_device_code(self):
            return _Login()

        def login_chatgpt(self):
            return _Login()

    monkeypatch.setattr("kite.providers.auth.codex.require_codex_sdk", lambda: None)
    monkeypatch.setattr("kite.providers.auth.codex._open_codex", lambda: _Codex())
    monkeypatch.setattr("kite.util.tty.is_interactive_tty", lambda **_k: False)
    opened: list[str] = []
    monkeypatch.setattr(
        "kite.providers.auth.ui.open_browser",
        lambda url: opened.append(url) or True,
    )
    with patch("kite.providers.byos.get_auth_provider", return_value=device_auth):
        msg = missing_credentials(resolve_model(provider="chatgpt"))
    assert msg and "kite login codex" in msg
    login_result = device_auth.login(console=None)
    assert login_result.exit_code == 0
    assert opened and opened[0].startswith("https://chatgpt.com/")
    project_env = tmp_path / ".env"
    project_env.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    chatgpt_spec = load_catalog().get("chatgpt")
    oauth_auth = CodexAuthProvider()
    with patch.object(oauth_auth, "login", return_value=LoginResult(0, "linked")):
        with patch("kite.providers.byos.get_auth_provider", return_value=oauth_auth):
            login_oauth(chatgpt_spec)
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


def test_model_selection_and_reasoning_levels(kite_home, monkeypatch) -> None:
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
    from kite.cli.slash import CommandIndex, SlashSpec
    from kite.models.reasoning import (
        ReasoningSupport,
        apply_reasoning,
        cycle_thinking_level,
        encode_reasoning,
        fallback_thinking_level,
        reasoning_to_thinking_level,
        resolve_thinking_level,
        split_reasoning,
        thinking_level_menu,
    )
    from kite.ui.complete import _visible_specs

    info = ReasoningSupport(True, True, True, True, thinking_kwargs={"reasoning_effort": "high"}, fast_kwargs={"reasoning_effort": "low"}, efforts=("none", "low", "medium", "high"))
    assert info.thinking_levels() == ("medium", "high")
    assert split_reasoning("thinking:high") == ("thinking", "high")
    assert encode_reasoning("thinking", "high") == "thinking:high"
    assert apply_reasoning({}, info, "thinking", effort="medium")["reasoning_effort"] == "medium"
    menu = thinking_level_menu(info)
    assert [pi for pi, _ in menu] == ["off", "low", "medium", "high"]
    assert resolve_thinking_level("high", info) == "thinking:high"
    assert resolve_thinking_level("low", info) == "fast:low"
    assert reasoning_to_thinking_level("thinking:high", info) == "high"
    assert cycle_thinking_level("off", info) == "fast:low"
    assert fallback_thinking_level("high") == "thinking:high"
    assert resolve_thinking_level("high", None) == "thinking:high"
    specs = {
        "thinking": SlashSpec("thinking", "control", "builtin", "t"),
        "fast": SlashSpec("fast", "control", "builtin", "f"),
        "reasoning": SlashSpec("reasoning", "control", "builtin", "r"),
    }
    index = CommandIndex(specs=specs)
    names = {s.name for s in _visible_specs(index, support=ReasoningSupport(True, False, True, True))}
    assert "thinking" in names and "reasoning" not in names and "fast" not in names
    names_off = {s.name for s in _visible_specs(index, support=ReasoningSupport(False, False, False, False))}
    # /thinking stays visible before detection warms — only levels are gated.
    assert "thinking" in names_off


def test_codex_litellm_flattens_and_materializes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.providers.auth import codex_litellm
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
    dest = token_dir / "auth.json"
    if os.name != "nt":
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    with patch.object(codex_litellm, "_write_private_json", wraps=codex_litellm._write_private_json) as writer:
        assert Path(codex_litellm.materialize_litellm_chatgpt_auth()) == token_dir
        writer.assert_not_called()
    (codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt"}), encoding="utf-8")
    with pytest.raises(CodexLitellmAuthError):
        codex_litellm.materialize_litellm_chatgpt_auth()


def test_oauth_status_cache_invalidation_and_expiry(monkeypatch) -> None:
    """Reuse fresh status verdicts; refresh after invalidation or TTL expiry."""
    from types import SimpleNamespace

    from kite.providers import byos

    now = 1000.0
    monkeypatch.setattr(byos, "time", SimpleNamespace(monotonic=lambda: now))

    auth = MagicMock()
    auth.provider_key = "chatgpt"
    auth.status.return_value = AuthStatus(True, "linked", account_label="a@x.com")
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", lambda *_a, **_k: auth)
    assert has_oauth_session("chatgpt") is True
    assert byos.oauth_session(load_catalog().get("chatgpt")).account_label == "a@x.com"
    assert auth.status.call_count == 1  # second call served from cache

    auth.status.return_value = AuthStatus(False, "not linked")
    assert has_oauth_session("chatgpt") is True  # stale within TTL
    byos.invalidate_auth_status_cache("chatgpt")
    assert has_oauth_session("chatgpt") is False
    assert auth.status.call_count == 2

    auth.status.return_value = AuthStatus(True, "linked again")
    now += byos._AUTH_STATUS_TTL + 1
    assert has_oauth_session("chatgpt") is True
    assert auth.status.call_count == 3


def test_resolve_stays_litellm_free(kite_home, monkeypatch) -> None:
    """Startup/completer resolve must never import LiteLLM (cold import blocks the composer)."""
    from kite.providers import capabilities
    from kite.providers.resolve import resolve_model as _resolve_model

    def _boom(model: str, provider: str):
        raise AssertionError("resolve must not consult LiteLLM")

    monkeypatch.setattr(capabilities, "_litellm_openai_params", _boom)
    assert agent_model_warning("my-custom-agent-model", local_only=True) is None
    assert agent_model_warning("text-embedding-3-small", local_only=True) is not None
    assert (
        agent_model_warning("custom-model", raw={"capabilities": {"tools": False}}, local_only=True)
        is not None
    )
    resolved = _resolve_model(provider="groq", model="llama-3.3-70b-versatile")
    assert (resolved.provider, resolved.model) == ("groq", "llama-3.3-70b-versatile")

    from kite.config import UserConfig
    from kite.config.readiness import assess_setup_status

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    cfg = UserConfig(default_provider="groq", default_model="custom-model")
    probes = []

    def configured(**kwargs):
        probes.append(kwargs)
        return [("groq", True, "GROQ_API_KEY"), ("ollama", True, "local")]

    monkeypatch.setattr("kite.providers.credentials.configured_providers", configured)
    assert _resolve_model(config=cfg).provider == "groq"
    assert probes == [], "a usable default must not probe unrelated subscription CLIs"
    status = assess_setup_status(config=cfg)
    assert status.ready and status.has_any_api_key and len(probes) == 1
    monkeypatch.delenv("GROQ_API_KEY")
    assert "kite keys --set groq" in missing_credentials(_resolve_model(provider="groq"))
    cfg.default_provider = "nim"
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-key")
    assert _resolve_model(config=cfg).provider == "nvidia"
    assert len(probes) == 1, "provider aliases must retain their configured default"


def test_model_capabilities_and_resolution_precedence(kite_home, monkeypatch) -> None:
    assert "No model selected" in agent_model_warning("")
    assert agent_model_warning("text-embedding-3-small") is not None
    assert agent_model_warning("my-custom-agent-model") is None
    assert agent_model_warning("custom-model", raw={"capabilities": {"tools": False}}) is not None
    assert model_supports_tools(raw={"supported_parameters": ["tools", "tool_choice"]}) is True
    assert model_supports_tools(raw={"capabilities": {"tools": True}}) is True
    assert model_supports_parallel_tool_calls(raw={"supported_parameters": ["parallel_tool_calls", "tools"]}) is True
    assert model_supports_parallel_tool_calls(raw={"capabilities": {"tools": False}}) is False
    from kite.config.user import UserConfig
    from kite.providers.resolve import resolve_model as _resolve_model

    cfg = UserConfig.load()
    cfg.default_provider = "groq"
    cfg.default_model = "llama-3.3-70b-versatile"
    cfg.provider_defaults = {}
    groq = _resolve_model(provider="groq", config=cfg)
    openai = _resolve_model(provider="openai", config=cfg)
    assert groq.model == "llama-3.3-70b-versatile"
    assert openai.provider == "openai"
    assert openai.model != "llama-3.3-70b-versatile"
    cfg.provider_defaults["openai"] = "gpt-per-provider"
    assert _resolve_model(provider="openai", config=cfg).model == "gpt-per-provider"
    assert _resolve_model(provider="openai", model="gpt-explicit", config=cfg).model == "gpt-explicit"

    catalog = load_catalog()
    for name in ("OPENAI_API_KEY", "OPENAI_COMPATIBLE_API_KEY", "CUSTOM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "gateway-key")
    assert api_key_for(catalog.get("openai-compatible")) == "gateway-key"
    monkeypatch.setenv("CUSTOM_API_KEY", "custom-key")
    assert api_key_for(catalog.get("openai-compatible")) == "gateway-key"
    monkeypatch.setenv("OPENAI_API_KEY", "primary-key")
    assert api_key_for(catalog.get("openai-compatible")) == "primary-key"
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY")
    assert api_key_for(catalog.get("openai-compatible")) == "custom-key"


def test_nvidia_nim_request_compatibility(monkeypatch, kite_home) -> None:
    from kite.config.user import UserConfig
    from kite.providers import capabilities
    from kite.providers.resolve import resolve_model as _resolve_model

    monkeypatch.setattr(capabilities, "_litellm_openai_params", lambda *_args, **_kwargs: None)
    assert (
        model_supports_parallel_tool_calls(
            provider="nvidia",
            model="meta/llama-3.1-70b-instruct",
            litellm_model="nvidia_nim/meta/llama-3.1-70b-instruct",
        )
        is False
    )
    assert (
        model_supports_parallel_tool_calls(
            provider="nvidia",
            model="meta/llama-3.1-70b-instruct",
            raw={"supported_parameters": ["parallel_tool_calls", "tools"]},
        )
        is True
    )
    assert (
        model_supports_parallel_tool_calls(
            provider="test",
            model="m",
            raw={"capabilities": {"tools": True, "parallel_tool_calls": True}},
        )
        is True
    )
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    cfg = UserConfig.load()
    cfg.provider_defaults = {}
    resolved = _resolve_model(provider="nvidia", model="meta/llama-3.1-70b-instruct", config=cfg)
    assert resolved.provider == "nvidia"
    assert resolved.litellm_model == "nvidia_nim/meta/llama-3.1-70b-instruct"
    assert resolved.api_base is None
    assert resolved.api_key == "nvapi-test-key"


def test_oauth_markers_fast_without_spawns(tmp_path, kite_home, monkeypatch) -> None:
    from kite.providers import byos
    from kite.providers.credentials import configured_providers

    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "auth.json").write_text('{"tokens": {"access_token": "x"}}', encoding="utf-8")
    assert byos.oauth_session_marker_present("chatgpt") is True
    assert byos.oauth_session_marker_present("codex") is True
    assert byos.oauth_session_marker_present("bogus") is False
    assert byos.oauth_session_marker_present("anthropic") is False
    (tmp_path / ".claude.json").write_text('{"oauth": {}}', encoding="utf-8")
    assert byos.oauth_session_marker_present("claude") is True

    bridge = kite_home / "oauth" / "xai"
    bridge.mkdir(parents=True)
    (bridge / "auth.json").write_text('{"access_token": "y"}', encoding="utf-8")
    assert byos.oauth_session_marker_present("grok") is True

    agy = kite_home / "oauth" / "antigravity"
    agy.mkdir(parents=True)
    (agy / "status.json").write_text('{"linked": true}', encoding="utf-8")
    assert byos.oauth_session_marker_present("antigravity") is True

    # Fast rows never touch probes: hard-fail if they try.
    monkeypatch.setattr(
        "kite.providers.credentials.inspect_provider_credentials",
        lambda _spec: (_ for _ in ()).throw(AssertionError("fast path must not probe")),
    )
    rows = {name: ok for name, ok, _ in configured_providers(fast=True)}
    assert rows["chatgpt"] is True
    assert rows["claude"] is True
    assert rows["grok"] is True
    assert rows["antigravity"] is True


def test_configured_providers_parallel_full_probes(kite_home, monkeypatch) -> None:
    import threading

    from kite.providers import byos
    from kite.providers.credentials import ProviderCredentialStatus, configured_providers

    expected = {spec.name for spec in load_catalog().list() if byos.is_oauth_provider(spec)}
    entered: list[str] = []
    completed: list[str] = []
    lock = threading.Lock()
    first_pair = threading.Barrier(2, timeout=1)

    def probe(spec):
        with lock:
            entered.append(spec.name)
            index = len(entered)
        if index <= 2:
            # Neither probe may finish until another probe runs concurrently.
            first_pair.wait()
        completed.append(spec.name)
        return ProviderCredentialStatus(
            provider=spec.name, linked=False, usable=False, method="oauth", detail="unlinked"
        )

    monkeypatch.setattr("kite.providers.credentials.inspect_provider_credentials", probe)
    rows = {name: ok for name, ok, _ in configured_providers()}
    assert set(completed) == expected
    assert len(entered) == len(expected)
    assert all(rows[name] is False for name in expected)


def test_antigravity_rides_on_gemini_key(kite_home, monkeypatch) -> None:
    """`kite login antigravity` + GEMINI_API_KEY must yield usable gemini access."""
    from kite.providers.byos import invalidate_auth_status_cache

    cat = load_catalog()
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    # conftest stubs every OAuth provider as unlinked — resolve reads the
    # stubbed verdict, so force the linked session at the resolve boundary.
    monkeypatch.setattr("kite.providers.resolve.has_oauth_session", lambda _p: True)
    try:
        assert api_key_for(cat.get("antigravity")) == "test-gemini-key"
        marker = kite_home / "oauth" / "antigravity"
        marker.mkdir(parents=True)
        (marker / "status.json").write_text(json.dumps({"linked": True}), encoding="utf-8")
        invalidate_auth_status_cache("antigravity")
        resolved = resolve_model(provider="antigravity", catalog=cat)
        assert resolved.api_key == "test-gemini-key"
        assert missing_credentials(resolved) is None
    finally:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        invalidate_auth_status_cache("antigravity")
    assert api_key_for(cat.get("antigravity")) is None
    # Linked without a key: subscription turns run via the agy CLI, so the
    # run is not blocked on credentials.
    resolved = resolve_model(provider="antigravity", catalog=cat)
    assert resolved.api_key is None
    assert missing_credentials(resolved) is None


