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
    if isinstance(spec_or_key, str):
        return _auth_by_name(spec_or_key)
    return get_auth_provider(_provider_key(spec_or_key))


def _auth_by_name(name: str) -> AuthProvider | None:
    """Resolve catalog names, login aliases, and oauth ids → auth provider.

    The auth registry is keyed by ``spec.oauth_provider`` (chatgpt, anthropic,
    xai) while callers may pass a catalog name (grok, claude) or a login alias
    (codex, xai→grok). Try each candidate, then fall back to the catalog's
    ``oauth_provider``.
    """
    raw = (name or "").strip().lower()
    if not raw:
        return None
    for key in dict.fromkeys((raw, resolve_login_provider(raw))):
        auth = get_auth_provider(key)
        if auth is not None:
            return auth
    from kite.providers.catalog import load_catalog

    try:
        spec = load_catalog().get(resolve_login_provider(raw))
    except KeyError:
        return None
    return get_auth_provider(spec.oauth_provider or spec.name)


def has_oauth_session(provider: str) -> bool:
    auth = _auth(provider)
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
    # Same for Grok: ~/.grok/auth.json is CLI-nested, LiteLLM needs it flat.
    if (spec.oauth_provider or spec.name) == "xai":
        from kite.providers.auth.grok_litellm import materialize_litellm_xai_auth

        materialize_litellm_xai_auth()
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

    from kite.config.onboarding import mark_setup_complete

    mark_setup_complete()
    _oauth_model_cache.pop(key, None)
    msg = result.message
    if set_default:
        from kite.providers.credentials import inspect_provider_credentials

        status = inspect_provider_credentials(spec)
        if status.usable:
            cfg = UserConfig.load()
            cfg.default_provider = spec.name
            if spec.default_model:
                cfg.default_model = spec.default_model
                cfg.provider_defaults[spec.name] = spec.default_model
            cfg.save()
            msg += f"  ·  default provider → {spec.name}"
        elif spec.oauth_provider == "anthropic":
            msg += "  ·  API key required for Kite — kite keys --set anthropic"
        elif spec.oauth_provider == "antigravity":
            msg += "  ·  API key required for Kite — kite keys --set gemini"

    return 0, msg, spec.name


_MATERIALIZED_OAUTH_DIRS = {
    "xai": "xai",
    "grok": "xai",
    "chatgpt": "chatgpt",
    "codex": "chatgpt",
    "openai": "chatgpt",
}
_MATERIALIZED_OAUTH_ENV = {
    "xai": ("XAI_OAUTH_TOKEN_DIR", "XAI_OAUTH_API_BASE"),
    "chatgpt": ("CHATGPT_TOKEN_DIR",),
}


def clear_materialized_oauth(spec: ProviderSpec) -> bool:
    """Drop Kite's flattened OAuth copy and the env vars that point at it."""
    key = resolve_login_provider(spec.oauth_provider or spec.name)
    sub = _MATERIALIZED_OAUTH_DIRS.get(key)
    removed = False
    if sub:
        from kite.config.user import kite_home

        folder = kite_home() / "oauth" / sub
        if folder.exists():
            import shutil

            shutil.rmtree(folder, ignore_errors=True)
            removed = not folder.exists()
        for env_key in _MATERIALIZED_OAUTH_ENV.get(sub, ()):
            if os.environ.pop(env_key, None) is not None:
                removed = True
    return removed


def logout_oauth(spec: ProviderSpec) -> bool:
    auth = _auth(spec)
    if auth is None:
        return False
    removed = auth.logout()
    removed = clear_materialized_oauth(spec) or removed
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
