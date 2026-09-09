"""OpenAI Codex / ChatGPT subscription auth via the official openai-codex SDK."""

from __future__ import annotations

import importlib.metadata
import shutil
from typing import TYPE_CHECKING

from kite.providers.auth.base import AuthStatus, LoginResult, sanitize_auth_message

if TYPE_CHECKING:
    from rich.console import Console

_CODEX_PACKAGE = "openai-codex"
_MIN_CODEX_VERSION = (0, 144, 4)
_FALLBACK_MODELS = ("gpt-5.6-luna", "gpt-5.4", "gpt-5.3-codex")


class CodexSdkError(Exception):
    """Codex SDK missing or incompatible."""


def _parse_version(raw: str) -> tuple[int, int, int]:
    parts = []
    for piece in raw.split(".")[:3]:
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def codex_sdk_version() -> str | None:
    try:
        return importlib.metadata.version(_CODEX_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return None


def require_codex_sdk() -> None:
    version = codex_sdk_version()
    if version is None:
        raise CodexSdkError(
            "openai-codex is not installed. Install Kite with Codex support: "
            "pip install 'openai-codex>=0.144.4'"
        )
    if _parse_version(version) < _MIN_CODEX_VERSION:
        raise CodexSdkError(
            f"openai-codex {version} is too old (need >= {_MIN_CODEX_VERSION[0]}.{_MIN_CODEX_VERSION[1]}.{_MIN_CODEX_VERSION[2]}). "
            "Upgrade: pip install -U 'openai-codex>=0.144.4'"
        )


def _codex_home() -> str:
    """Codex credential directory (~/.codex). LiteLLM chatgpt OAuth reads CHATGPT_TOKEN_DIR."""
    from pathlib import Path

    return str(Path.home() / ".codex")


def _open_codex():
    require_codex_sdk()
    from openai_codex import Codex

    return Codex()


def _account_authenticated(account_response) -> bool:
    if account_response is None:
        return False
    account = getattr(account_response, "account", None)
    if account is None:
        return False
    # RootModel — unwrap ChatGPT / API key account payloads.
    root = getattr(account, "root", account)
    return root is not None


def _account_label(account_response) -> str:
    account = getattr(account_response, "account", None)
    if account is None:
        return ""
    root = getattr(account, "root", account)
    for attr in ("email", "account_id", "plan_type", "type"):
        val = getattr(root, attr, None)
        if val:
            return str(val)
    return ""


class CodexAuthProvider:
    provider_key = "chatgpt"

    def status(self) -> AuthStatus:
        try:
            with _open_codex() as codex:
                resp = codex.account()
        except CodexSdkError as exc:
            return AuthStatus(False, str(exc), method="subscription")
        except Exception as exc:  # noqa: BLE001
            return AuthStatus(
                False,
                sanitize_auth_message(f"Codex is not linked. {exc}"),
                method="subscription",
            )

        if _account_authenticated(resp):
            label = _account_label(resp)
            msg = "ChatGPT / Codex subscription linked."
            if label:
                msg += f" Account: {label}."
            return AuthStatus(True, msg, account_label=label, method="subscription")
        return AuthStatus(
            False,
            "Codex is not linked. Run: kite login codex (or kite login chatgpt).",
            method="subscription",
        )

    def login(self, *, device: bool = False, console: Console | None = None) -> LoginResult:
        from kite.providers.auth.ui import open_browser, show_byos_panel, wait_with_status
        from kite.providers.catalog import load_catalog
        from kite.util.tty import is_interactive_tty

        spec = load_catalog().get("chatgpt")

        current_status = self.status()
        if current_status.authenticated:
            return LoginResult(0, "ChatGPT / Codex subscription already linked.")

        try:
            require_codex_sdk()
        except CodexSdkError as exc:
            return LoginResult(2, str(exc))

        try:
            with _open_codex() as codex:
                use_device = device or not is_interactive_tty(require_stdout=False)

                if use_device:
                    login = codex.login_chatgpt_device_code()
                    url = login.verification_url
                    user_code = login.user_code
                    opened = False
                else:
                    login = codex.login_chatgpt()
                    url = login.auth_url
                    user_code = ""
                    opened = open_browser(url)

                show_byos_panel(
                    spec,
                    url=url,
                    console=console,
                    user_code=user_code,
                    browser_opened=opened if not use_device else False,
                    extra="Opening ChatGPT sign-in…" if not use_device else "",
                )

                def _wait():
                    result = login.wait()
                    if not getattr(result, "success", True):
                        raise RuntimeError("ChatGPT sign-in was not completed.")
                    return result

                wait_with_status(
                    console,
                    "Waiting for you to authenticate in the browser…",
                    _wait,
                )

                after = codex.account()
                if not _account_authenticated(after):
                    return LoginResult(2, "ChatGPT sign-in failed — Codex account is still unlinked.")
                return LoginResult(0, "ChatGPT / Codex subscription linked.")
        except KeyboardInterrupt:
            return LoginResult(130, "cancelled")
        except CodexSdkError as exc:
            return LoginResult(2, str(exc))
        except Exception as exc:  # noqa: BLE001
            return LoginResult(2, sanitize_auth_message(f"ChatGPT sign-in failed: {exc}"))

    def logout(self) -> bool:
        try:
            with _open_codex() as codex:
                if not _account_authenticated(codex.account()):
                    return False
                codex.logout()
                return True
        except Exception:
            return False

    def fetch_model_ids(self) -> tuple[str, ...]:
        try:
            with _open_codex() as codex:
                if not _account_authenticated(codex.account()):
                    return _FALLBACK_MODELS
                resp = codex.models()
                rows = getattr(resp, "models", None) or getattr(resp, "data", None) or []
                ids: list[str] = []
                for row in rows:
                    slug = (
                        getattr(row, "slug", None)
                        or getattr(row, "id", None)
                        or getattr(row, "name", None)
                        or (row.get("slug") if isinstance(row, dict) else None)
                        or (row.get("id") if isinstance(row, dict) else None)
                    )
                    if not slug:
                        continue
                    text = str(slug).removeprefix("chatgpt/")
                    if isinstance(row, dict):
                        if row.get("visibility") == "hidden":
                            continue
                        if row.get("enabled") is False:
                            continue
                    ids.append(text)
                if ids:
                    return tuple(dict.fromkeys(ids))
        except Exception:
            pass
        return _FALLBACK_MODELS

    def litellm_env(self) -> dict[str, str]:
        # Codex CLI stores nested tokens under ~/.codex/auth.json; LiteLLM needs a
        # flat auth.json. Bridge into ~/.kite/oauth/chatgpt (see codex_litellm).
        from kite.providers.auth.codex_litellm import litellm_chatgpt_env

        return litellm_chatgpt_env()

    def litellm_extras(self) -> dict[str, object]:
        return {}


def codex_cli_available() -> bool:
    return shutil.which("codex") is not None
