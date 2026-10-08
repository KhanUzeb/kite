"""Secure ~/.kite/.env credential storage."""

from __future__ import annotations

import os
import stat

import pytest
from rich.console import Console

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


@pytest.fixture(autouse=True)
def _isolate_credentials(workspace, kite_home, monkeypatch) -> None:
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("kite.providers.credentials._ENV_LOADED_KEY", None)
    for name in (
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_API_KEY",
        "NGC_API_KEY",
        "FIRECRAWL_API_KEY",
        "TAVILY_API_KEY",
        "EXA_API_KEY",
        "TINYFISH_API_KEY",
        "OTHER",
    ):
        # delenv alone records nothing for an absent key. Register it first
        # so direct write_api_key/load_kite_env mutations are also undone.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name, raising=False)


def test_write_api_key_replaces_existing_and_secures_files(kite_home, monkeypatch) -> None:
    env = kite_home / ".env"
    env.write_text("OPENAI_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    write_api_key("OPENAI_API_KEY", "new-secret")
    text = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=new-secret" in text
    assert "OTHER=1" in text
    assert "old" not in text
    assert os.environ["OPENAI_API_KEY"] == "new-secret"
    if os.name != "nt":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
    env2 = kite_home / ".env2"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env2)
    write_api_key("GROQ_API_KEY", "secret")
    if os.name != "nt":
        mode = stat.S_IMODE(env2.stat().st_mode)
        assert mode == 0o600


def test_remove_api_key_removes_process_value_and_orphan_header(kite_home, monkeypatch) -> None:
    env = kite_home / ".env"
    env.write_text("GROQ_API_KEY=abc\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "abc")
    assert remove_api_key("GROQ_API_KEY") is True
    assert "GROQ_API_KEY" not in env.read_text(encoding="utf-8")
    assert "GROQ_API_KEY" not in os.environ
    # write_api_key stores a '# VAR' header — logout must not leave it orphaned.
    env2 = kite_home / ".env2"
    env2.write_text("OTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env2)
    write_api_key("GROQ_API_KEY", "secret-value-123")
    assert "# GROQ_API_KEY" in env2.read_text(encoding="utf-8")
    assert remove_api_key("GROQ_API_KEY") is True
    text = env2.read_text(encoding="utf-8")
    assert "GROQ_API_KEY" not in text
    assert "OTHER=1" in text
    assert "GROQ_API_KEY" not in os.environ
    assert remove_api_key("GROQ_API_KEY") is False


def test_load_kite_env_reloads_changes_and_fills_project_placeholders(
    workspace, kite_home, monkeypatch
) -> None:
    (workspace / ".env").write_text(
        "GROQ_API_KEY=\nOPENAI_API_KEY=from-project\n", encoding="utf-8"
    )
    home_env = kite_home / ".env"
    home_env.write_text(
        "GROQ_API_KEY=from-kite-home\nOPENAI_API_KEY=from-home\n", encoding="utf-8"
    )
    load_kite_env()
    assert os.getenv("GROQ_API_KEY") == "from-kite-home"
    assert os.getenv("OPENAI_API_KEY") == "from-project"

    # Same-mtime rewrites on coarse filesystems must not serve stale keys.
    st = home_env.stat()
    home_env.write_text("GROQ_API_KEY=replaced-with-longer-key\n", encoding="utf-8")
    os.utime(home_env, (st.st_atime, st.st_mtime))
    monkeypatch.delenv("GROQ_API_KEY")
    load_kite_env()
    assert os.getenv("GROQ_API_KEY") == "replaced-with-longer-key"


def test_login_provider_removes_alias_and_accepts_web_keys(
    kite_home, monkeypatch, caplog, capsys
) -> None:
    caplog.set_level("DEBUG")
    env = kite_home / ".env"
    env.write_text("NGC_API_KEY=old-alias\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: "new-primary-key")
    from kite.providers.credentials import login_provider

    code, msg, name = login_provider("nvidia", set_default=False, console=Console())
    assert code == 0
    assert name == "nvidia"
    text = env.read_text(encoding="utf-8")
    assert "NGC_API_KEY" not in text
    assert "NVIDIA_API_KEY=new-primary-key" in text
    assert "OTHER=1" in text
    assert "NGC_API_KEY" not in os.environ
    output = capsys.readouterr()
    assert "new-primary-key" not in msg + caplog.text + output.out + output.err
    env2 = kite_home / ".env2"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env2)
    monkeypatch.setattr(
        "kite.providers.credentials.read_secret",
        lambda _p: "fc-test-key-abcdefghij",
    )
    from kite.providers.credentials import web_tool_api_key

    code, msg, name = login_provider("firecrawl", set_default=False, console=Console())
    assert code == 0
    assert name == "firecrawl"
    assert web_tool_api_key("firecrawl") == "fc-test-key-abcdefghij"
    assert "FIRECRAWL_API_KEY" in msg
    output = capsys.readouterr()
    assert "fc-test-key-abcdefghij" not in msg + caplog.text + output.out + output.err


def test_api_key_validation_and_confirmation_mismatch(monkeypatch) -> None:
    assert validate_api_key("") == "API key cannot be empty"
    assert validate_api_key("valid-key-123") is None
    prompts = iter(["first-key-ok", "second-key-bad"])
    monkeypatch.setattr("kite.providers.credentials.read_secret", lambda _p: next(prompts))
    secret, err = prompt_api_key("GROQ_API_KEY", replacing=False)
    assert secret is None
    assert err == "keys did not match — nothing saved"


def test_api_key_fingerprint_masks_set_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_abcdefgh")
    assert api_key_fingerprint(load_catalog().get("groq")) == "••••efgh"
    assert mask_api_key_fingerprint("sk-abcdefghijklmnop") == "••••mnop"


def test_web_tool_login_logout_secures_keys_without_logging_secrets(
    kite_home, monkeypatch, caplog, capsys
) -> None:
    caplog.set_level("DEBUG")
    env = kite_home / ".env"
    monkeypatch.setattr(
        "kite.providers.credentials.read_secret",
        lambda _p: "tvly-test-key-abcdefgh",
    )
    from kite.providers.credentials import login_web_tool_key, web_tool_api_key

    code, msg, name = login_web_tool_key("tavily", console=Console())
    assert code == 0
    assert name == "tavily"
    assert "TAVILY_API_KEY=tvly-test-key-abcdefgh" in env.read_text(encoding="utf-8")
    assert web_tool_api_key("tavily") == "tvly-test-key-abcdefgh"
    assert "••••efgh" in msg
    output = capsys.readouterr()
    assert "tvly-test-key-abcdefgh" not in msg + caplog.text + output.out + output.err
    if os.name != "nt":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
    env.write_text("EXA_API_KEY=exa-secret-key\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setenv("EXA_API_KEY", "exa-secret-key")
    from kite.providers.credentials import logout_web_tool_key

    out_code, out_msg = logout_web_tool_key("exa")
    assert out_code == 0
    assert "removed" in out_msg
    assert "EXA_API_KEY" not in env.read_text(encoding="utf-8")
    assert "OTHER=1" in env.read_text(encoding="utf-8")
    assert web_tool_api_key("exa") is None


def test_configured_web_tool_keys_distinguishes_saved_and_missing_keys(kite_home) -> None:
    env = kite_home / ".env"
    env.write_text("TAVILY_API_KEY=tvly-abcdefg-xyz\n", encoding="utf-8")
    from kite.providers.credentials import configured_web_tool_keys

    rows = {n: (ok, env_var) for n, ok, env_var in configured_web_tool_keys()}
    assert rows["tavily"][0] is True
    assert rows["tavily"][1] == "TAVILY_API_KEY"
    assert rows["exa"][0] is False
    assert rows["firecrawl"][0] is False
