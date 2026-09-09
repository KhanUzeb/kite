"""Codex CLI auth.json → LiteLLM flat auth bridge (ChatGPT BYOS hang fix)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_flatten_codex_nested_tokens() -> None:
    from kite.providers.auth.codex_litellm import flatten_codex_auth_record

    nested = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": "access-abc",
            "refresh_token": "refresh-xyz",
            "id_token": "id-123",
            "account_id": "acct-1",
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    }
    flat = flatten_codex_auth_record(nested)
    assert flat["access_token"] == "access-abc"
    assert flat["refresh_token"] == "refresh-xyz"
    assert flat["id_token"] == "id-123"
    assert flat["account_id"] == "acct-1"


def test_flatten_already_flat_passthrough() -> None:
    from kite.providers.auth.codex_litellm import flatten_codex_auth_record

    flat_in = {
        "access_token": "a",
        "refresh_token": "r",
        "id_token": "i",
        "account_id": "acct",
        "expires_at": 9999999999,
    }
    assert flatten_codex_auth_record(flat_in)["access_token"] == "a"


def test_materialize_writes_litellm_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.providers.auth import codex_litellm

    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "tok",
                    "refresh_token": "ref",
                    "id_token": "idt",
                    "account_id": "acc",
                },
            }
        ),
        encoding="utf-8",
    )
    kite_home = tmp_path / "kite"
    kite_home.mkdir()
    monkeypatch.setattr(codex_litellm, "_codex_home", lambda: str(codex_home))
    monkeypatch.setattr(codex_litellm, "_kite_chatgpt_token_dir", lambda: kite_home / "oauth" / "chatgpt")

    token_dir = codex_litellm.materialize_litellm_chatgpt_auth()
    assert token_dir == str(kite_home / "oauth" / "chatgpt")
    auth = json.loads((Path(token_dir) / "auth.json").read_text(encoding="utf-8"))
    assert auth["access_token"] == "tok"
    assert "tokens" not in auth


def test_materialize_missing_tokens_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.providers.auth import codex_litellm
    from kite.providers.auth.codex_litellm import CodexLitellmAuthError

    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt"}), encoding="utf-8")
    monkeypatch.setattr(codex_litellm, "_codex_home", lambda: str(codex_home))
    monkeypatch.setattr(codex_litellm, "_kite_chatgpt_token_dir", lambda: tmp_path / "out")

    with pytest.raises(CodexLitellmAuthError, match="LiteLLM cannot read OAuth tokens"):
        codex_litellm.materialize_litellm_chatgpt_auth()


def test_codex_litellm_env_points_at_materialized_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kite.providers.auth.codex import CodexAuthProvider
    from kite.providers.auth import codex_litellm

    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "tok",
                    "refresh_token": "ref",
                    "id_token": "idt",
                    "account_id": "acc",
                }
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "kite-oauth"
    monkeypatch.setattr(codex_litellm, "_codex_home", lambda: str(codex_home))
    monkeypatch.setattr(codex_litellm, "_kite_chatgpt_token_dir", lambda: out)
    monkeypatch.setattr("kite.providers.auth.codex._codex_home", lambda: str(codex_home))

    env = CodexAuthProvider().litellm_env()
    assert env["CHATGPT_TOKEN_DIR"] == str(out)
    assert (out / "auth.json").is_file()
    # Must not leave CHATGPT_TOKEN_DIR on raw ~/.codex (nested tokens hang LiteLLM).
    assert env["CHATGPT_TOKEN_DIR"] != str(codex_home)
