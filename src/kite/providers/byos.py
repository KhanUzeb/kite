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

# OAuth status probes are slow (Codex SDK ~1.4s, `claude auth status` up to
# ~25s on hangs) — `configured_providers()` runs them concurrently, caches
# verdicts briefly, and offers marker-only fast verdicts for startup paths.
# Login and logout invalidate explicitly so transitions stay exact.
_AUTH_STATUS_TTL = 120.0
_auth_status_cache: dict[tuple[str, str], tuple[float, Any]] = {}

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


def _status_cache_key(key: str) -> tuple[str, str]:
    from kite.config.user import kite_home

    try:
        home = str(kite_home())
    except OSError:
        home = ""
    return (home, key)


def _cached_status(key: str) -> Any | None:
    """Fresh cached AuthStatus for an oauth provider key, if any."""
    hit = _auth_status_cache.get(_status_cache_key(key))
    if hit and (time.monotonic() - hit[0]) < _AUTH_STATUS_TTL:
        return hit[1]
    return None


def invalidate_auth_status_cache(provider: str | None = None) -> None:
    """Drop cached OAuth verdicts — call after login/logout transitions."""
    if provider is None:
        _auth_status_cache.clear()
        return
    for cache_key in [k for k in _auth_status_cache if k[1] == provider]:
        _auth_status_cache.pop(cache_key, None)


def has_oauth_session(provider: str) -> bool:
    auth = _auth(provider)
    if auth is None:
        return False
    key = getattr(auth, "provider_key", provider)
    cached = _cached_status(key)
    if cached is not None:
        return bool(cached.authenticated)
    status = auth.status()
    _auth_status_cache[_status_cache_key(key)] = (time.monotonic(), status)
    return status.authenticated


def _nontrivial(path: Any) -> bool:
    """A credential file that exists and is not an empty placeholder."""
    try:
        return bool(path.is_file()) and path.stat().st_size > 2
    except (OSError, TypeError, AttributeError):
        return False


def oauth_session_marker_present(provider: str) -> bool:
    """No-spawn linked-session hint for startup/completion fast paths.

    Checks only credential marker files — no CLI/SDK subprocesses, no
    network. A stale-true (expired tokens on disk) only affects startup
    hints; login flows and turn-time ``missing_credentials`` still run the
    authoritative ``status()`` probe.
    """
    from pathlib import Path

    key = (provider or "").strip().lower()
    # A probe verdict from this process (login/logout just ran) beats markers.
    try:
        auth = _auth(provider)
        resolved = getattr(auth, "provider_key", key) if auth is not None else key
        if isinstance(resolved, str) and resolved.strip():
            key = resolved.strip().lower()
    except Exception:
        pass
    # Accept catalog names and login aliases, not just oauth ids.
    # (Intentionally not resolve_login_provider: its "xai"→"grok" login
    # shorthand points the wrong way for oauth ids.)
    key = {
        "chatgpt": "chatgpt",
        "codex": "chatgpt",
        "chatgpt-sub": "chatgpt",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "claude-sub": "anthropic",
        "xai": "xai",
        "grok": "xai",
        "grok-sub": "xai",
        "antigravity": "antigravity",
        "antigravity-sub": "antigravity",
    }.get(key, key)
    try:
        cached = _cached_status(key)
        if cached is not None:
            return bool(cached.authenticated)
    except Exception:
        pass
    try:
        home = Path.home()
    except Exception:
        return False
    try:
        if key == "chatgpt":
            from kite.config.user import kite_home

            return _nontrivial(home / ".codex" / "auth.json") or _nontrivial(
                kite_home() / "oauth" / "chatgpt" / "auth.json"
            )
        if key == "xai":
            override = os.environ.get("GROK_HOME")
            grok_home = Path(override).expanduser() if override else home / ".grok"
            from kite.config.user import kite_home

            return _nontrivial(grok_home / "auth.json") or _nontrivial(
                kite_home() / "oauth" / "xai" / "auth.json"
            )
        if key == "anthropic":
            return _nontrivial(home / ".claude.json")
        if key == "antigravity":
            from kite.config.user import kite_home

            marker = kite_home() / "oauth" / "antigravity" / "status.json"
            if not _nontrivial(marker):
                return False
            try:
                import json

                data = json.loads(marker.read_text(encoding="utf-8"))
                return bool(isinstance(data, dict) and data.get("linked"))
            except (OSError, ValueError):
                return False
    except Exception:
        return False
    return False


def oauth_session(spec: ProviderSpec) -> OAuthSession | None:
    auth = _auth(spec)
    if auth is None:
        return None
    key = getattr(auth, "provider_key", _provider_key(spec))
    cached = _cached_status(key)
    status = cached if cached is not None else auth.status()
    if cached is None:
        _auth_status_cache[_status_cache_key(key)] = (time.monotonic(), status)
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
    invalidate_auth_status_cache(key)
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
    invalidate_auth_status_cache(_provider_key(spec))
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
        key = getattr(auth, "provider_key", _provider_key(spec))
        status = _cached_status(key)
        if status is None:
            status = auth.status()
            _auth_status_cache[_status_cache_key(key)] = (time.monotonic(), status)
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
