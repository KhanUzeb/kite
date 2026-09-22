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


def test_write_api_key_combined(tmp_path, monkeypatch) -> None:
    # (merged from test_write_api_key_replaces_existing)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    write_api_key("OPENAI_API_KEY", "new-secret")
    text = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=new-secret" in text
    assert "OTHER=1" in text
    # (merged from test_write_api_key_sets_owner_only_mode)
    env2 = tmp_path / ".env2"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env2)
    write_api_key("GROQ_API_KEY", "secret")
    if os.name != "nt":
        mode = stat.S_IMODE(env2.stat().st_mode)
        assert mode == 0o600


def test_remove_api_key_combined(tmp_path, monkeypatch) -> None:
    # (merged from test_remove_api_key)
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=abc\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setenv("GROQ_API_KEY", "abc")
    assert remove_api_key("GROQ_API_KEY") is True
    assert "GROQ_API_KEY" not in env.read_text(encoding="utf-8")
    # (merged from test_remove_api_key_drops_header_comment)
    # write_api_key stores a '# VAR' header — logout must not leave it orphaned.
    env2 = tmp_path / ".env2"
    env2.write_text("OTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env2)
    write_api_key("GROQ_API_KEY", "secret-value-123")
    assert "# GROQ_API_KEY" in env2.read_text(encoding="utf-8")
    assert remove_api_key("GROQ_API_KEY") is True
    text = env2.read_text(encoding="utf-8")
    assert "GROQ_API_KEY" not in text
    assert "OTHER=1" in text


def test_load_kite_env_combined(tmp_path, monkeypatch) -> None:
    # (merged from test_load_kite_env_fills_empty_project_placeholder)
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
    # (merged from test_load_kite_env_reloads_after_rewrite_without_mtime_change)
    # Same-mtime rewrites (coarse filesystems) must not serve stale keys.
    import kite.providers.credentials as creds

    home_env = tmp_path / "kite-home.env"
    home_env.write_text("RELOAD_KEY=one\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: home_env)
    proj = tmp_path / "proj2"
    proj.mkdir()
    monkeypatch.chdir(proj)
    monkeypatch.setattr(creds, "_ENV_LOADED_KEY", None)
    monkeypatch.delenv("RELOAD_KEY", raising=False)
    load_kite_env()
    assert os.getenv("RELOAD_KEY") == "one"
    st = home_env.stat()
    home_env.write_text("RELOAD_KEY=two-much-longer\n", encoding="utf-8")
    os.utime(home_env, (st.st_atime, st.st_mtime))
    monkeypatch.delenv("RELOAD_KEY", raising=False)
    load_kite_env()
    assert os.getenv("RELOAD_KEY") == "two-much-longer"


def test_login_provider_alias_cleanup_combined(tmp_path, monkeypatch) -> None:
    # (merged from test_login_provider_removes_alias_keys_from_env_file)
    env = tmp_path / ".env"
    env.write_text("NGC_API_KEY=old-alias\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: "new-primary-key")
    from kite.providers.credentials import login_provider

    code, msg, name = login_provider("nvidia", set_default=False, console=None)
    assert code == 0
    assert name == "nvidia"
    assert "NGC_API_KEY" not in env.read_text(encoding="utf-8")
    # (merged from test_keys_set_accepts_web_tool_alias)
    env2 = tmp_path / ".env2"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env2)
    monkeypatch.setattr(
        "kite.providers.credentials.read_secret",
        lambda _p: "fc-test-key-abcdefghij",
    )
    from kite.providers.credentials import web_tool_api_key

    code, msg, name = login_provider("firecrawl", set_default=False, console=None)
    assert code == 0
    assert name == "firecrawl"
    assert web_tool_api_key("firecrawl") == "fc-test-key-abcdefghij"
    assert "FIRECRAWL_API_KEY" in msg


def test_api_key_validation_and_prompt_combined(monkeypatch) -> None:
    # (merged from test_validate_api_key_rejects_empty_and_short)
    assert validate_api_key("") == "API key cannot be empty"
    assert validate_api_key("valid-key-123") is None
    # (merged from test_prompt_api_key_requires_matching_confirm)
    prompts = iter(["first-key-ok", "second-key-bad"])
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: next(prompts))
    secret, err = prompt_api_key("GROQ_API_KEY", replacing=False)
    assert secret is None
    assert err == "keys did not match — nothing saved"


def test_api_key_fingerprint_masks_set_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_abcdefgh")
    assert api_key_fingerprint(load_catalog().get("groq")) == "••••efgh"
    assert mask_api_key_fingerprint("sk-abcdefghijklmnop") == "••••mnop"


def test_web_tool_login_logout_combined(tmp_path, monkeypatch) -> None:
    # (merged from test_login_web_tool_key_writes_secure_env)
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
    # (merged from test_logout_web_tool_key_removes_env)
    env.write_text("EXA_API_KEY=exa-secret-key\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    monkeypatch.setenv("EXA_API_KEY", "exa-secret-key")
    from kite.providers.credentials import logout_web_tool_key

    out_code, out_msg = logout_web_tool_key("exa")
    assert out_code == 0
    assert "removed" in out_msg
    assert "EXA_API_KEY" not in env.read_text(encoding="utf-8")
    assert "OTHER=1" in env.read_text(encoding="utf-8")
    assert web_tool_api_key("exa") is None


def test_web_keys_cli_and_status_combined(tmp_path, monkeypatch) -> None:
    # (merged from test_web_keys_cli_parser_registered)
    from kite.cli.run import build_parser

    parser = build_parser()
    args = parser.parse_args(["web-keys", "set", "tavily"])
    assert args.web_keys_cmd == "set"
    assert args.name == "tavily"
    args2 = parser.parse_args(["web-keys"])
    assert args2.web_keys_cmd == "status"
    args3 = parser.parse_args(["keys", "--set", "exa"])
    assert args3.set == "exa"
    # (merged from test_configured_web_tool_keys_reports_status)
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
