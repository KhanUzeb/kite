"""Secure ~/.kite/.env credential storage."""

from __future__ import annotations

import os
import stat

from kite.providers.credentials import (
    env_file_path,
    remove_api_key,
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
