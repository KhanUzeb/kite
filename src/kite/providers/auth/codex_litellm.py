"""Bridge official Codex CLI auth.json into LiteLLM's flat ChatGPT auth format.

Codex stores::

    {"auth_mode": "chatgpt", "tokens": {"access_token": "...", ...}}

LiteLLM's ``chatgpt/`` Authenticator expects top-level fields::

    {"access_token": "...", "refresh_token": "...", "id_token": "...", "account_id": "..."}

Pointing ``CHATGPT_TOKEN_DIR`` at ``~/.codex`` therefore makes LiteLLM miss the
session and start an interactive device-code login — which hangs the Kite
harness. We sync a flat copy under ``~/.kite/oauth/chatgpt`` instead.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

_log = logging.getLogger("kite.providers.auth.codex_litellm")


class CodexLitellmAuthError(RuntimeError):
    """Codex session linked for Kite, but no LiteLLM-usable tokens on disk."""


def _codex_home() -> str:
    from kite.providers.auth.codex import _codex_home as _home

    return _home()


def _kite_chatgpt_token_dir() -> Path:
    from kite.config.user import ensure_home, kite_home

    ensure_home()
    path = kite_home() / "oauth" / "chatgpt"
    path.mkdir(parents=True, exist_ok=True)
    return path


def flatten_codex_auth_record(data: dict[str, Any]) -> dict[str, Any]:
    """Return LiteLLM-shaped auth fields from Codex or already-flat JSON."""
    tokens = data.get("tokens")
    if isinstance(tokens, dict) and tokens.get("access_token"):
        src = tokens
    elif data.get("access_token"):
        src = data
    else:
        return {}

    out: dict[str, Any] = {}
    for key in ("access_token", "refresh_token", "id_token", "account_id", "expires_at"):
        val = src.get(key)
        if val is not None and val != "":
            out[key] = val
    # Prefer account_id from nested tokens, then top-level Codex record.
    if "account_id" not in out and data.get("account_id"):
        out["account_id"] = data["account_id"]
    return out


def _read_codex_auth_file(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def materialize_litellm_chatgpt_auth() -> str:
    """Sync Codex CLI tokens into a LiteLLM-flat auth.json; return token dir.

    Raises CodexLitellmAuthError when no usable tokens are available (e.g.
    credentials only in the OS keyring with an empty auth.json).
    """
    codex_path = Path(_codex_home()) / "auth.json"
    data = _read_codex_auth_file(codex_path)
    flat = flatten_codex_auth_record(data or {})
    if not flat.get("access_token"):
        raise CodexLitellmAuthError(
            "ChatGPT/Codex is linked, but LiteLLM cannot read OAuth tokens from "
            f"{codex_path}. Codex nests tokens under \"tokens\"; if credentials "
            "live only in the OS keyring, set cli_auth_credentials_store = \"file\" "
            "in ~/.codex/config.toml and run: kite login chatgpt"
        )

    dest_dir = _kite_chatgpt_token_dir()
    dest = dest_dir / "auth.json"
    _write_private_json(dest, flat)
    _log.debug("materialized LiteLLM ChatGPT auth at %s", dest)
    return str(dest_dir)


def litellm_chatgpt_env() -> dict[str, str]:
    """Env vars for LiteLLM chatgpt/ — always the flattened Kite token dir."""
    token_dir = materialize_litellm_chatgpt_auth()
    return {"CHATGPT_TOKEN_DIR": token_dir}
