"""BYOS — Bring Your Own Subscription (OAuth), not per-token API billing."""

from __future__ import annotations

import json
import os
import stat
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kite.config.user import ensure_home, kite_home
from kite.providers.catalog import ProviderSpec

if TYPE_CHECKING:
    from rich.console import Console

_OAUTH_MODEL_TTL = 300.0  # 5 min — matches Codex client cache cadence
_oauth_model_cache: dict[str, tuple[float, tuple[str, ...]]] = {}


def clear_oauth_model_cache(provider: str | None = None) -> None:
    if provider:
        _oauth_model_cache.pop(provider, None)
        return
    _oauth_model_cache.clear()

OAuthModelFetcher = Callable[[], tuple[str, ...]]

ANTHROPIC_OAUTH_PREFIX = "sk-ant-oat"


@dataclass(frozen=True)
class OAuthSession:
    access_token: str
    account_id: str | None = None
    refresh_token: str | None = None


def oauth_token_dir(provider: str) -> Path:
    ensure_home()
    path = kite_home() / "oauth" / provider
    path.mkdir(parents=True, exist_ok=True)
    return path


def oauth_auth_file(provider: str) -> Path:
    return oauth_token_dir(provider) / "auth.json"


def _secure(path: Path) -> None:
    if path.is_file():
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def _write_auth(provider: str, data: dict[str, Any]) -> None:
    path = oauth_auth_file(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _secure(path)


def _read_auth(provider: str) -> dict[str, Any] | None:
    path = oauth_auth_file(provider)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def has_oauth_session(provider: str) -> bool:
    data = _read_auth(provider)
    return bool(data and data.get("access_token"))


def _chatgpt_authenticator():
    """LiteLLM OAuth SDK — device flow + refresh."""
    from litellm.llms.chatgpt.authenticator import Authenticator

    token_dir = str(oauth_token_dir("chatgpt"))
    os.environ["CHATGPT_TOKEN_DIR"] = token_dir
    auth = Authenticator()
    auth.token_dir = token_dir
    auth.auth_file = str(oauth_auth_file("chatgpt"))
    return auth


def _xai_authenticator():
    from litellm.llms.xai.oauth import XAIOAuthAuthenticator

    token_dir = str(oauth_token_dir("xai"))
    os.environ["XAI_OAUTH_TOKEN_DIR"] = token_dir
    auth = XAIOAuthAuthenticator()
    auth.token_dir = token_dir
    auth.auth_file = str(oauth_auth_file("xai"))
    return auth


def _claude_credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _import_claude_cli_credentials() -> dict[str, Any] | None:
    """Import Claude Code / Claude.ai OAuth from the official CLI store."""
    path = _claude_credentials_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    oauth = raw.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    access = str(oauth.get("accessToken") or "").strip()
    if not access.startswith(ANTHROPIC_OAUTH_PREFIX):
        return None
    refresh = str(oauth.get("refreshToken") or "").strip() or None
    expires_at = oauth.get("expiresAt")
    try:
        expires_at = int(expires_at) if expires_at is not None else None
    except (TypeError, ValueError):
        expires_at = None
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": expires_at,
        "source": "claude-cli",
    }


def _sync_anthropic_from_claude_cli() -> dict[str, Any] | None:
    imported = _import_claude_cli_credentials()
    if imported is None:
        return _read_auth("anthropic")
    data = _read_auth("anthropic") or {}
    stored = str(data.get("access_token") or "")
    if stored != imported["access_token"]:
        _write_auth("anthropic", imported)
        return imported
    return data if data.get("access_token") else imported


def oauth_session(spec: ProviderSpec) -> OAuthSession | None:
    """Load a fresh access token via the provider OAuth SDK."""
    key = spec.oauth_provider or spec.name
    if key == "chatgpt":
        if not has_oauth_session("chatgpt"):
            return None
        try:
            auth = _chatgpt_authenticator()
            token = auth.get_access_token()
            if not token:
                return None
            data = _read_auth("chatgpt") or {}
            return OAuthSession(
                access_token=token,
                account_id=auth.get_account_id() or data.get("account_id"),
                refresh_token=data.get("refresh_token"),
            )
        except Exception:
            return None
    if key == "xai":
        if not has_oauth_session("xai"):
            return None
        try:
            auth = _xai_authenticator()
            token = auth.get_access_token()
            if not token:
                return None
            data = _read_auth("xai") or {}
            return OAuthSession(
                access_token=token,
                refresh_token=data.get("refresh_token"),
            )
        except Exception:
            return None
    if key == "anthropic":
        data = _sync_anthropic_from_claude_cli()
        if not data or not data.get("access_token"):
            return None
        return OAuthSession(
            access_token=str(data["access_token"]),
            refresh_token=data.get("refresh_token"),
        )
    return None


def oauth_access_token(spec: ProviderSpec) -> str | None:
    session = oauth_session(spec)
    return session.access_token if session else None


def ensure_oauth_env(spec: ProviderSpec) -> None:
    """Point LiteLLM OAuth backends at ~/.kite/oauth/<provider>."""
    key = spec.oauth_provider or spec.name
    if key == "chatgpt":
        os.environ["CHATGPT_TOKEN_DIR"] = str(oauth_token_dir("chatgpt"))
    elif key == "xai":
        os.environ["XAI_OAUTH_TOKEN_DIR"] = str(oauth_token_dir("xai"))


def oauth_litellm_extras(spec: ProviderSpec) -> dict[str, Any]:
    """Extra LiteLLM kwargs for subscription providers."""
    key = spec.oauth_provider or spec.name
    if key == "xai":
        return {"use_xai_oauth": True}
    if key == "anthropic":
        token = oauth_access_token(spec)
        return {"api_key": token} if token else {}
    return {}


def _litellm_chatgpt_fallback() -> tuple[str, ...]:
    try:
        import litellm

        models = sorted(
            str(m).removeprefix("chatgpt/") for m in getattr(litellm, "chatgpt_models", set())
        )
        if models:
            return tuple(models)
    except Exception:
        pass
    return ("gpt-5.6-luna", "gpt-5.4", "gpt-5.3-codex")


def _fetch_chatgpt_models_live() -> tuple[str, ...]:
    """GET /backend-api/codex/models with the user's OAuth token."""
    session = oauth_session(
        ProviderSpec(
            name="chatgpt",
            display_name="ChatGPT",
            kind="chatgpt",
            litellm_prefix="chatgpt/",
            base_url="",
            api_key_env="",
            models=(),
            default_model="",
            auth_kind="oauth",
            oauth_provider="chatgpt",
        )
    )
    if session is None:
        return _litellm_chatgpt_fallback()

    try:
        from litellm.llms.chatgpt.common_utils import get_chatgpt_default_headers

        auth = _chatgpt_authenticator()
        api_base = auth.get_api_base().rstrip("/")
        client_version = "0.101.0"
        headers = get_chatgpt_default_headers(
            session.access_token,
            session.account_id,
        )
        headers["accept"] = "application/json"
        req = urllib.request.Request(
            f"{api_base}/models?client_version={client_version}",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return _litellm_chatgpt_fallback()

    entries = data.get("models") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return _litellm_chatgpt_fallback()

    ids: list[str] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or row.get("id") or row.get("name") or "").strip()
        if not slug:
            continue
        if row.get("visibility") == "hidden":
            continue
        if row.get("enabled") is False:
            continue
        ids.append(slug.removeprefix("chatgpt/"))

    if not ids:
        return _litellm_chatgpt_fallback()
    return tuple(dict.fromkeys(ids))


def _xai_fallback_models() -> tuple[str, ...]:
    return ("grok-4.6", "grok-4", "grok-3")


def _fetch_xai_models_live() -> tuple[str, ...]:
    session = oauth_session(
        ProviderSpec(
            name="grok",
            display_name="Grok",
            kind="xai",
            litellm_prefix="xai/",
            base_url="",
            api_key_env="",
            models=(),
            default_model="",
            auth_kind="oauth",
            oauth_provider="xai",
        )
    )
    if session is None:
        return _xai_fallback_models()
    try:
        from litellm.llms.xai.common_utils import XAIModelInfo

        auth = _xai_authenticator()
        info = XAIModelInfo()
        rows = info.get_models(api_key=session.access_token, api_base=auth.get_api_base())
        ids = [str(m).removeprefix("xai/") for m in rows if m]
        if ids:
            return tuple(dict.fromkeys(ids))
    except Exception:
        pass
    return _xai_fallback_models()


def _anthropic_fallback_models() -> tuple[str, ...]:
    return ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5")


def _fetch_anthropic_models_live() -> tuple[str, ...]:
    session = oauth_session(
        ProviderSpec(
            name="claude",
            display_name="Claude",
            kind="anthropic",
            litellm_prefix="anthropic/",
            base_url="https://api.anthropic.com",
            api_key_env="",
            models=(),
            default_model="",
            auth_kind="oauth",
            oauth_provider="anthropic",
        )
    )
    if session is None:
        return _anthropic_fallback_models()
    base = "https://api.anthropic.com"
    url = f"{base}/v1/models"
    headers = {
        "x-api-key": session.access_token,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return _anthropic_fallback_models()

    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return _anthropic_fallback_models()
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "").strip()
        if mid:
            ids.append(mid)
    if not ids:
        return _anthropic_fallback_models()
    return tuple(dict.fromkeys(ids))


_OAUTH_MODEL_FETCHERS: dict[str, OAuthModelFetcher] = {
    "chatgpt": _fetch_chatgpt_models_live,
    "xai": _fetch_xai_models_live,
    "anthropic": _fetch_anthropic_models_live,
}


def register_oauth_model_fetcher(provider: str, fetcher: OAuthModelFetcher) -> None:
    _OAUTH_MODEL_FETCHERS[provider] = fetcher


def fetch_oauth_model_ids(spec: ProviderSpec, *, refresh: bool = False) -> tuple[str, ...]:
    """Dynamic model list from the provider's OAuth API (cached)."""
    key = spec.oauth_provider or spec.name
    fetcher = _OAUTH_MODEL_FETCHERS.get(key)
    if fetcher is None:
        return tuple(spec.models)

    now = time.monotonic()
    if not refresh:
        hit = _oauth_model_cache.get(key)
        if hit and now - hit[0] < _OAUTH_MODEL_TTL:
            return hit[1]

    models = fetcher()
    _oauth_model_cache[key] = (now, models)
    return models


def _open_browser(url: str) -> bool:
    import webbrowser

    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError:
            return False
    return False


def _show_byos_panel(
    spec: ProviderSpec,
    *,
    url: str,
    console: Console | None,
    user_code: str = "",
    browser_opened: bool | None = False,
    extra: str = "",
) -> None:
    from kite.ui.credentials import render_byos_login_panel

    panel = render_byos_login_panel(
        spec,
        url=url,
        user_code=user_code,
        browser_opened=browser_opened,
        extra=extra,
    )
    if console is not None:
        console.print(panel)
        return
    print(str(panel), flush=True)


def _wait(console: Console | None, message: str, work):
    if console is not None:
        with console.status(message):
            return work()
    return work()


def login_oauth(
    spec: ProviderSpec,
    *,
    set_default: bool = False,
    console: Console | None = None,
) -> tuple[int, str, str | None]:
    """Run OAuth device/browser flow for a subscription provider."""
    from kite.config import UserConfig

    provider = spec.oauth_provider or spec.name
    if provider == "chatgpt":
        code, msg = _login_chatgpt_oauth(spec, console=console)
    elif provider == "xai":
        code, msg = _login_xai_oauth(spec, console=console)
    elif provider == "anthropic":
        code, msg = _login_anthropic_oauth(spec, console=console)
    else:
        return 2, f"OAuth not implemented for '{provider}'", None

    if code != 0:
        return code, msg, None

    _oauth_model_cache.pop(provider, None)
    if set_default:
        cfg = UserConfig.load()
        cfg.default_provider = spec.name
        if spec.default_model:
            cfg.default_model = spec.default_model
            cfg.provider_defaults[spec.name] = spec.default_model
        cfg.save()
        msg += f"  ·  default provider → {spec.name}"

    return 0, msg, spec.name


def _login_chatgpt_oauth(spec: ProviderSpec, *, console: Console | None) -> tuple[int, str]:
    try:
        from litellm.llms.chatgpt.common_utils import CHATGPT_DEVICE_VERIFY_URL

        auth = _chatgpt_authenticator()
        if has_oauth_session("chatgpt"):
            token = auth.get_access_token()
            if token:
                return 0, f"ChatGPT subscription already linked → {auth.auth_file}"

        if console is not None:
            console.print("[dim]Starting ChatGPT device login…[/]")
        device = auth._request_device_code()
        auth._record_device_code_request()
        user_code = str(device.get("user_code") or "")
        verify = CHATGPT_DEVICE_VERIFY_URL
        browse = f"{verify}?user_code={user_code}" if user_code else verify
        opened = _open_browser(browse)
        _show_byos_panel(
            spec,
            url=verify,
            console=console,
            user_code=user_code,
            browser_opened=opened,
        )
        auth_code = _wait(
            console,
            "Waiting for you to authenticate in the browser…",
            lambda: auth._poll_for_authorization_code(device),
        )
        tokens = auth._exchange_code_for_tokens(auth_code)
        auth._write_auth_file(auth._build_auth_record(tokens))
        _secure(Path(auth.auth_file))
        if not auth.get_access_token():
            return 2, "ChatGPT OAuth login failed — no access token"
        return 0, f"ChatGPT subscription linked → {auth.auth_file}"
    except KeyboardInterrupt:
        return 130, "cancelled"
    except Exception as exc:  # noqa: BLE001
        return 2, f"ChatGPT OAuth login failed: {exc}"


def _login_xai_oauth(spec: ProviderSpec, *, console: Console | None) -> tuple[int, str]:
    try:
        auth = _xai_authenticator()
        if has_oauth_session("xai"):
            token = auth.get_access_token()
            if token:
                return 0, f"Grok subscription already linked → {auth.auth_file}"

        _show_byos_panel(
            spec,
            url="https://auth.x.ai",
            console=console,
            extra="Complete sign-in in the browser, then return here.",
            browser_opened=None,
        )
        _wait(console, "Waiting for xAI sign-in in your browser…", lambda: auth.login(force=True))
        _secure(Path(auth.auth_file))
        if not auth.get_access_token():
            return 2, "xAI OAuth login failed — no access token"
        return 0, f"Grok subscription linked → {auth.auth_file}"
    except KeyboardInterrupt:
        return 130, "cancelled"
    except Exception as exc:  # noqa: BLE001
        return 2, f"xAI OAuth login failed: {exc}"


def _prompt_claude_token(console: Console | None) -> str | None:
    from kite.util.tty import is_interactive_tty

    if not is_interactive_tty(require_stdout=False):
        return None
    try:
        from rich.prompt import Prompt

        raw = Prompt.ask(
            "Paste token from `claude setup-token` (hidden, Enter to skip)",
            password=True,
            default="",
            console=console,
        )
    except (EOFError, KeyboardInterrupt):
        return None
    token = (raw or "").strip()
    return token or None


def _login_anthropic_oauth(spec: ProviderSpec, *, console: Console | None) -> tuple[int, str]:
    imported = _import_claude_cli_credentials()
    if imported is not None:
        _write_auth("anthropic", imported)
        return 0, f"Claude subscription linked from {_claude_credentials_path()}"

    opened = _open_browser("https://claude.ai")
    _show_byos_panel(
        spec,
        url="https://claude.ai",
        console=console,
        browser_opened=opened,
        extra="Sign in, then run `claude setup-token` and paste the token here — or log in with Claude Code first.",
    )
    pasted = _prompt_claude_token(console)
    if pasted:
        if not pasted.startswith(ANTHROPIC_OAUTH_PREFIX):
            return 2, f"That doesn't look like a Claude OAuth token (expected {ANTHROPIC_OAUTH_PREFIX}…)"
        _write_auth("anthropic", {"access_token": pasted, "source": "pasted"})
        return 0, f"Claude subscription linked → {oauth_auth_file('anthropic')}"

    imported = _import_claude_cli_credentials()
    if imported is not None:
        _write_auth("anthropic", imported)
        return 0, f"Claude subscription linked from {_claude_credentials_path()}"

    claude_path = _claude_credentials_path()
    return (
        2,
        "Claude OAuth not found. Sign in at claude.ai, run `claude setup-token` and "
        f"paste the token, or log in with Claude Code (creates {claude_path}).",
    )


def logout_oauth(spec: ProviderSpec) -> bool:
    provider = spec.oauth_provider or spec.name
    path = oauth_auth_file(provider)
    removed = False
    if path.is_file():
        path.unlink()
        removed = True
    _oauth_model_cache.pop(provider, None)
    return removed


def is_oauth_provider(spec: ProviderSpec) -> bool:
    return spec.auth_kind == "oauth"


def is_subscription_provider(spec: ProviderSpec) -> bool:
    return spec.auth_kind in {"oauth", "subscription"}


def is_byok_provider(spec: ProviderSpec) -> bool:
    """API-key providers eligible for live model picker."""
    return not is_oauth_provider(spec) and spec.auth_kind != "subscription"


def credential_label(spec: ProviderSpec) -> str:
    if spec.auth_kind == "oauth":
        return "oauth"
    if spec.auth_kind == "subscription":
        return "subscription"
    return spec.api_key_env or "—"


def subscription_login_hint(spec: ProviderSpec) -> str:
    return (
        f"{spec.display_name} subscription not linked. "
        f"Run: kite login {spec.name} (or /login {spec.name} in the REPL). "
        f"Uses OAuth — not API credits."
    )
