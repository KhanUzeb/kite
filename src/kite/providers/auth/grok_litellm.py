"""Bridge official Grok CLI auth.json into LiteLLM's flat xAI OAuth format.

Grok CLI stores::

    {"https://auth.x.ai::<client-uuid>": {"key": "<access jwt>", "refresh_token": "...",
     "expires_at": "<iso8601>", ...}}

LiteLLM's ``xai/`` ``XAIOAuthAuthenticator`` expects top-level fields::

    {"access_token": "...", "refresh_token": "...", "expires_at": <epoch seconds>,
     "token_endpoint": "https://..."}}

Pointing ``XAI_OAUTH_TOKEN_DIR`` at ``~/.grok`` therefore makes LiteLLM miss the
session and raise "xAI OAuth login required" on every call — even right after
``kite login grok``. We sync a flat copy under ``~/.kite/oauth/xai`` instead.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger("kite.providers.auth.grok_litellm")

_XAI_OAUTH_DISCOVERY_URL = "https://auth.x.ai/.well-known/openid-configuration"

# SuperGrok subscription calls go through xAI's chat proxy — api.x.ai is
# BYOK-only and answers subscription tokens with 403.
_XAI_SUBSCRIPTION_API_BASE = "https://cli-chat-proxy.grok.com/v1"

# The proxy 426s requests without a client version stamp (reverse-engineered
# from the official CLI). Read live via `grok --version`, else this fallback.
_GROK_VERSION_FALLBACK = "1.0.13"
_grok_version_cache: str | None = None


def grok_client_version() -> str:
    """Official CLI version for the proxy's client-version header (cached)."""
    global _grok_version_cache
    if _grok_version_cache:
        return _grok_version_cache
    import re
    import shutil
    import subprocess

    version = _GROK_VERSION_FALLBACK
    grok_bin = shutil.which("grok")
    if grok_bin:
        try:
            proc = subprocess.run(
                [grok_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            match = re.search(r"grok\s+(\d+\.\d+\.\d+)", proc.stdout or "")
            if match:
                version = match.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    _grok_version_cache = version
    return version


def xai_subscription_headers() -> dict[str, str]:
    """Extra headers the subscription proxy requires (else 426)."""
    return {"x-grok-client-version": grok_client_version()}


class GrokLitellmAuthError(RuntimeError):
    """Grok is linked for Kite, but no LiteLLM-usable tokens are on disk."""


def _kite_xai_token_dir() -> Path:
    from kite.config.user import ensure_home, kite_home

    ensure_home()
    path = kite_home() / "oauth" / "xai"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json_file(path: Path) -> dict[str, Any] | None:
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
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _write_private_json_if_changed(path: Path, payload: dict[str, Any]) -> None:
    """Write flattened auth only when it differs — this runs every model turn."""
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == json.dumps(payload, indent=2):
            return
    except OSError:
        pass
    _write_private_json(path, payload)


def _grok_entry(data: dict[str, Any]) -> dict[str, Any]:
    """Pick the usable session record from grok-CLI (or already-flat) JSON."""
    if data.get("access_token"):
        return data
    for value in data.values():
        if isinstance(value, dict) and value.get("key"):
            return value
    return {}


def _epoch_or_none(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from datetime import UTC

        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _discover_token_endpoint() -> str | None:
    """Fetch the xAI OIDC token endpoint so offline refreshes keep working."""
    try:
        with urllib.request.urlopen(_XAI_OAUTH_DISCOVERY_URL, timeout=15) as resp:
            payload = json.loads(resp.read(65536).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — discovery is best-effort
        _log.debug("xAI OIDC discovery failed: %s", exc)
        return None
    endpoint = payload.get("token_endpoint") if isinstance(payload, dict) else None
    return str(endpoint) if endpoint else None


def flatten_grok_auth_record(data: dict[str, Any]) -> dict[str, Any]:
    """Return LiteLLM-shaped auth fields from grok-CLI or already-flat JSON."""
    src = _grok_entry(data)
    access = src.get("access_token") or src.get("key")
    if not access:
        return {}
    out: dict[str, Any] = {"access_token": access}
    refresh = src.get("refresh_token")
    if refresh:
        out["refresh_token"] = refresh
    for key in ("id_token", "token_type", "token_endpoint"):
        val = src.get(key)
        if val is not None and val != "":
            out[key] = val
    expires_at = _epoch_or_none(src.get("expires_at"))
    if expires_at is not None:
        out["expires_at"] = expires_at
    return out


def materialize_litellm_xai_auth() -> str:
    """Sync Grok CLI tokens into a LiteLLM-flat auth.json; return token dir.

    Raises GrokLitellmAuthError when no usable tokens exist (grok not linked).
    Refresh is handled by LiteLLM afterwards — it writes back to this copy,
    so the grok CLI store is never clobbered.
    """
    from kite.providers.auth.grok import grok_auth_file

    grok_path = grok_auth_file()
    data = _read_json_file(grok_path)
    flat = flatten_grok_auth_record(data or {})
    if not flat.get("access_token"):
        raise GrokLitellmAuthError(
            "Grok subscription is not linked (or the Grok CLI keeps credentials "
            f"outside {grok_path}). Run: kite login grok"
        )
    if not flat.get("token_endpoint"):
        endpoint = _discover_token_endpoint()
        if endpoint:
            flat["token_endpoint"] = endpoint

    dest_dir = _kite_xai_token_dir()
    _write_private_json_if_changed(dest_dir / "auth.json", flat)
    _log.debug("materialized LiteLLM xAI auth at %s", dest_dir / "auth.json")
    return str(dest_dir)


def litellm_xai_env() -> dict[str, str]:
    """Env vars for LiteLLM xai/ — always the flattened Kite token dir."""
    token_dir = materialize_litellm_xai_auth()
    return {
        "XAI_OAUTH_TOKEN_DIR": token_dir,
        "XAI_OAUTH_API_BASE": _XAI_SUBSCRIPTION_API_BASE,
    }
