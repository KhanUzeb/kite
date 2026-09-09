"""BYOS — Bring Your Own Subscription (OAuth), not per-token API billing."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kite.providers.auth import get_auth_provider, resolve_login_provider
from kite.providers.auth.base import AuthProvider
from kite.providers.catalog import ProviderSpec

if TYPE_CHECKING:
    from rich.console import Console

_OAUTH_MODEL_TTL = 300.0
_oauth_model_cache: dict[str, tuple[float, tuple[str, ...]]] = {}

OAuthModelFetcher = Callable[[], tuple[str, ...]]


@dataclass(frozen=True)
class OAuthSession:
    """Presence marker for linked subscription — no secret material."""

    linked: bool
    account_label: str = ""


def clear_oauth_model_cache(provider: str | None = None) -> None:
    if provider:
        _oauth_model_cache.pop(provider, None)
        return
    _oauth_model_cache.clear()


def _provider_key(spec: ProviderSpec) -> str:
    return spec.oauth_provider or spec.name


def _auth(spec_or_key: ProviderSpec | str) -> AuthProvider | None:
    key = spec_or_key if isinstance(spec_or_key, str) else _provider_key(spec_or_key)
    return get_auth_provider(key)


def has_oauth_session(provider: str) -> bool:
    auth = _auth(resolve_login_provider(provider))
    if auth is None:
        return False
    return auth.status().authenticated


def oauth_session(spec: ProviderSpec) -> OAuthSession | None:
    auth = _auth(spec)
    if auth is None:
        return None
    status = auth.status()
    if not status.authenticated:
        return None
    return OAuthSession(linked=True, account_label=status.account_label)


def oauth_access_token(spec: ProviderSpec) -> str | None:
    """BYOS providers do not expose OAuth tokens to Kite's model layer."""
    return None


def ensure_oauth_env(spec: ProviderSpec) -> None:
    auth = _auth(spec)
    if auth is None:
        return
    # ChatGPT BYOS: materialize flat LiteLLM auth before exporting env — otherwise
    # LiteLLM starts an interactive device-code login and the harness hangs.
    if (spec.oauth_provider or spec.name) == "chatgpt":
        from kite.providers.auth.codex_litellm import materialize_litellm_chatgpt_auth

        materialize_litellm_chatgpt_auth()
    for key, val in auth.litellm_env().items():
        os.environ[key] = val


def oauth_litellm_extras(spec: ProviderSpec) -> dict[str, Any]:
    auth = _auth(spec)
    if auth is None:
        return {}
    return dict(auth.litellm_extras())


_OAUTH_MODEL_FETCHERS: dict[str, OAuthModelFetcher] = {}


def _default_fetcher(key: str) -> OAuthModelFetcher:
    def _fetch() -> tuple[str, ...]:
        auth = get_auth_provider(key)
        return auth.fetch_model_ids() if auth else ()

    return _fetch


def register_oauth_model_fetcher(provider: str, fetcher: OAuthModelFetcher) -> None:
    _OAUTH_MODEL_FETCHERS[provider] = fetcher


def fetch_oauth_model_ids(spec: ProviderSpec, *, refresh: bool = False) -> tuple[str, ...]:
    key = _provider_key(spec)
    fetcher = _OAUTH_MODEL_FETCHERS.get(key) or _default_fetcher(key)

    now = time.monotonic()
    if not refresh:
        hit = _oauth_model_cache.get(key)
        if hit and now - hit[0] < _OAUTH_MODEL_TTL:
            return hit[1]

    models = fetcher()
    _oauth_model_cache[key] = (now, models)
    return models


def login_oauth(
    spec: ProviderSpec,
    *,
    set_default: bool = False,
    console: Console | None = None,
    device: bool = False,
) -> tuple[int, str, str | None]:
    from kite.config import UserConfig

    key = _provider_key(spec)
    auth = _auth(spec)
    if auth is None:
        return 2, f"OAuth not implemented for '{key}'", None

    result = auth.login(device=device, console=console)
    if result.exit_code != 0:
        return result.exit_code, result.message, None

    _oauth_model_cache.pop(key, None)
    msg = result.message
    if set_default:
        cfg = UserConfig.load()
        cfg.default_provider = spec.name
        if spec.default_model:
            cfg.default_model = spec.default_model
            cfg.provider_defaults[spec.name] = spec.default_model
        cfg.save()
        msg += f"  ·  default provider → {spec.name}"

    return 0, msg, spec.name


def logout_oauth(spec: ProviderSpec) -> bool:
    auth = _auth(spec)
    if auth is None:
        return False
    removed = auth.logout()
    _oauth_model_cache.pop(_provider_key(spec), None)
    return removed


def is_oauth_provider(spec: ProviderSpec) -> bool:
    return spec.auth_kind == "oauth"


def is_subscription_provider(spec: ProviderSpec) -> bool:
    return spec.auth_kind in {"oauth", "subscription"}


def is_byok_provider(spec: ProviderSpec) -> bool:
    return not is_oauth_provider(spec) and spec.auth_kind != "subscription"


def credential_label(spec: ProviderSpec) -> str:
    if spec.auth_kind == "oauth":
        return "oauth"
    if spec.auth_kind == "subscription":
        return "subscription"
    return spec.api_key_env or "—"


def subscription_login_hint(spec: ProviderSpec) -> str:
    auth = _auth(spec)
    if auth is not None:
        status = auth.status()
        if status.message and not status.authenticated:
            return status.message
    return (
        f"{spec.display_name} subscription not linked. "
        f"Run: kite login {spec.name} (or /login {spec.name} in the REPL). "
        f"Uses your subscription plan — not API credits."
    )


# Legacy paths kept for tests that patch oauth_auth_file — metadata only, never tokens.
def oauth_token_dir(provider: str) -> str:
    from kite.config.user import ensure_home, kite_home

    ensure_home()
    path = kite_home() / "oauth" / resolve_login_provider(provider)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def oauth_auth_file(provider: str):
    from pathlib import Path

    return Path(oauth_token_dir(provider)) / "status.json"
