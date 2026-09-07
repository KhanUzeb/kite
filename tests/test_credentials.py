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
    assert "OPENAI_API_KEY=old" not in text
    assert "OTHER=1" in text


def test_write_api_key_appends_when_missing(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    write_api_key("GROQ_API_KEY", "abc")
    assert "GROQ_API_KEY=abc" in env.read_text(encoding="utf-8")


def test_write_api_key_quotes_special_chars(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    write_api_key("OPENAI_API_KEY", "sk-with spaces")
    assert 'OPENAI_API_KEY="sk-with spaces"' in env.read_text(encoding="utf-8")


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
    text = env.read_text(encoding="utf-8")
    assert "GROQ_API_KEY" not in text
    assert "OTHER=1" in text
    assert os.getenv("GROQ_API_KEY") is None


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


def test_load_kite_env_project_key_wins_over_kite_home(tmp_path, monkeypatch) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / ".env").write_text("GROQ_API_KEY=from-project\n", encoding="utf-8")
    kite_env = tmp_path / "kite" / ".env"
    kite_env.parent.mkdir()
    kite_env.write_text("GROQ_API_KEY=from-kite-home\n", encoding="utf-8")
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: kite_env)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    load_kite_env()
    assert os.getenv("GROQ_API_KEY") == "from-project"


def test_logout_provider(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("NVIDIA_API_KEY=nv-secret\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    from kite.providers.credentials import logout_provider

    code, msg = logout_provider("nvidia")
    assert code == 0
    assert "removed" in msg
    if env.is_file():
        assert "NVIDIA_API_KEY" not in env.read_text(encoding="utf-8")
    else:
        assert not env.exists()


def test_login_provider_removes_alias_keys_from_env_file(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("NGC_API_KEY=old-alias\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("kite.providers.credentials.env_file_path", lambda: env)
    calls: list[str] = []

    def _read_secret(prompt: str) -> str | None:
        calls.append(prompt)
        return "new-primary-key"

    monkeypatch.setattr("kite.providers.credentials.read_secret", _read_secret)

    from kite.providers.credentials import login_provider

    code, msg, name = login_provider("nvidia", set_default=False, console=None)
    assert code == 0
    assert name == "nvidia"
    assert len(calls) == 2  # new key: enter + confirm
    assert "••••" in msg
    text = env.read_text(encoding="utf-8")
    assert "NVIDIA_API_KEY=new-primary-key" in text
    assert "NGC_API_KEY" not in text
    assert "OTHER=1" in text


def test_validate_api_key_rejects_empty_and_short() -> None:
    assert validate_api_key("") == "API key cannot be empty"
    assert validate_api_key("short") == "API key looks too short — check for typos"
    assert validate_api_key("valid-key-123") is None


def test_mask_api_key_fingerprint() -> None:
    assert mask_api_key_fingerprint("sk-abcdefghijklmnop") == "••••mnop"


def test_prompt_api_key_requires_matching_confirm(monkeypatch) -> None:
    prompts = iter(["first-key-ok", "second-key-bad"])

    def _read(_prompt: str) -> str | None:
        return next(prompts)

    monkeypatch.setattr("kite.providers.credentials.read_secret", _read)
    secret, err = prompt_api_key("GROQ_API_KEY", replacing=False)
    assert secret is None
    assert err == "keys did not match — nothing saved"


def test_prompt_api_key_replacing_skips_confirm(monkeypatch) -> None:
    monkeypatch.setattr(
        "kite.providers.credentials.read_secret",
        lambda _prompt: "replacement-key-ok",
    )
    secret, err = prompt_api_key("GROQ_API_KEY", replacing=True)
    assert err is None
    assert secret == "replacement-key-ok"


def test_api_key_fingerprint_masks_set_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_abcdefgh")
    spec = load_catalog().get("groq")
    assert api_key_fingerprint(spec) == "••••efgh"
