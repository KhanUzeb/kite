"""Secure ~/.kite/.env credential storage."""

from __future__ import annotations

import os
import stat

from kite.providers.catalog import load_catalog
from kite.providers.credentials import (
    api_key_fingerprint,
    load_kite_env,
    mask_api_key_fingerprint,
    prompt_api_key,
    remove_api_key,
    validate_api_key,
    write_api_key,
)


def test_write_api_key_replaces_existing(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    write_api_key("OPENAI_API_KEY", "new-secret")
    text = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=new-secret" in text
    assert "OTHER=1" in text


def test_write_api_key_sets_owner_only_mode(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    write_api_key("GROQ_API_KEY", "secret")
    if os.name != "nt":
        mode = stat.S_IMODE(env.stat().st_mode)
        assert mode == 0o600


def test_remove_api_key(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=abc\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setenv("GROQ_API_KEY", "abc")
    assert remove_api_key("GROQ_API_KEY") is True
    assert "GROQ_API_KEY" not in env.read_text(encoding="utf-8")


def test_load_kite_env_fills_empty_project_placeholder(tmp_path, monkeypatch) -> None:
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


def test_login_provider_removes_alias_keys_from_env_file(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("NGC_API_KEY=old-alias\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: "new-primary-key")
    from kite.providers.credentials import login_provider

    code, msg, name = login_provider("nvidia", set_default=False, console=None)
    assert code == 0
    assert name == "nvidia"
    assert "NGC_API_KEY" not in env.read_text(encoding="utf-8")


def test_validate_api_key_rejects_empty_and_short() -> None:
    assert validate_api_key("") == "API key cannot be empty"
    assert validate_api_key("valid-key-123") is None


def test_prompt_api_key_requires_matching_confirm(monkeypatch) -> None:
    prompts = iter(["first-key-ok", "second-key-bad"])
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: next(prompts))
    secret, err = prompt_api_key("GROQ_API_KEY", replacing=False)
    assert secret is None
    assert err == "keys did not match — nothing saved"


def test_api_key_fingerprint_masks_set_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_abcdefgh")
    assert api_key_fingerprint(load_catalog().get("groq")) == "••••efgh"
    assert mask_api_key_fingerprint("sk-abcdefghijklmnop") == "••••mnop"


def test_login_web_tool_key_writes_secure_env(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setattr(
        "kite.providers.credentials.read_secret",
        lambda _p: "tvly-test-key-abcdefgh",
    )
    from kite.providers.credentials import login_web_tool_key, web_tool_api_key

    code, msg, name = login_web_tool_key("tavily", console=None)
    assert code == 0
    assert name == "tavily"
    assert "TAVILY_API_KEY=tvly-test-key-abcdefgh" in env.read_text(encoding="utf-8")
    assert web_tool_api_key("tavily") == "tvly-test-key-abcdefgh"
    assert "••••efgh" in msg
    if os.name != "nt":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_logout_web_tool_key_removes_env(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("EXA_API_KEY=exa-secret-key\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setenv("EXA_API_KEY", "exa-secret-key")
    from kite.providers.credentials import logout_web_tool_key, web_tool_api_key

    code, msg = logout_web_tool_key("exa")
    assert code == 0
    assert "removed" in msg
    assert "EXA_API_KEY" not in env.read_text(encoding="utf-8")
    assert "OTHER=1" in env.read_text(encoding="utf-8")
    assert web_tool_api_key("exa") is None


def test_keys_set_accepts_web_tool_alias(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setattr(
        "kite.providers.credentials.read_secret",
        lambda _p: "fc-test-key-abcdefghij",
    )
    from kite.providers.credentials import login_provider, web_tool_api_key

    code, msg, name = login_provider("firecrawl", set_default=False, console=None)
    assert code == 0
    assert name == "firecrawl"
    assert web_tool_api_key("firecrawl") == "fc-test-key-abcdefghij"
    assert "FIRECRAWL_API_KEY" in msg


def test_web_keys_cli_parser_registered() -> None:
    from kite.cli.run import build_parser

    parser = build_parser()
    args = parser.parse_args(["web-keys", "set", "tavily"])
    assert args.web_keys_cmd == "set"
    assert args.name == "tavily"
    args2 = parser.parse_args(["web-keys"])
    assert args2.web_keys_cmd == "status"
    args3 = parser.parse_args(["keys", "--set", "exa"])
    assert args3.set == "exa"


def test_configured_web_tool_keys_reports_status(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("TAVILY_API_KEY=tvly-abcdefg-xyz\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abcdefg-xyz")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    from kite.providers.credentials import configured_web_tool_keys

    rows = {n: (ok, env_var) for n, ok, env_var in configured_web_tool_keys()}
    assert rows["tavily"][0] is True
    assert rows["tavily"][1] == "TAVILY_API_KEY"
    assert rows["exa"][0] is False
    assert rows["firecrawl"][0] is False
