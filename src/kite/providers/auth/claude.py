"""Claude Code subscription auth — delegated to the official Claude Code CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

from kite.providers.auth.base import AuthStatus, LoginResult, sanitize_auth_message
from kite.providers.auth.cli import run_cli

if TYPE_CHECKING:
    from rich.console import Console

_CLAUDE_BIN = "claude"
_FALLBACK_MODELS = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5")
_SUBSCRIPTION_HINT = (
    "Claude subscription authentication is handled by Claude Code. "
    'Run `claude auth login` (or `kite login claude`), or configure ANTHROPIC_API_KEY for API access.'
)


def claude_cli_path() -> str | None:
    return shutil.which(_CLAUDE_BIN)


def _run_claude_auth(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return run_cli(_CLAUDE_BIN, *args, timeout=timeout)


def _parse_auth_status_json(stdout: str) -> dict[str, Any] | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def claude_auth_status() -> AuthStatus:
    if claude_cli_path() is None:
        return AuthStatus(
            False,
            "Claude Code CLI is not installed. Install from https://docs.anthropic.com/claude-code "
            "or use ANTHROPIC_API_KEY (kite keys --set anthropic).",
            method="subscription",
        )

    try:
        proc = _run_claude_auth("auth", "status", "--json", timeout=15.0)
    except FileNotFoundError:
        return AuthStatus(False, _SUBSCRIPTION_HINT, method="subscription")
    except subprocess.TimeoutExpired:
        return AuthStatus(False, "Claude Code auth status timed out.", method="subscription")
    except OSError as exc:
        return AuthStatus(False, sanitize_auth_message(str(exc)), method="subscription")

    if proc.returncode == 0:
        payload = _parse_auth_status_json(proc.stdout) or {}
        email = str(payload.get("email") or payload.get("accountEmail") or "").strip()
        method = str(payload.get("authMethod") or payload.get("loginMethod") or "subscription")
        msg = "Claude Code subscription linked."
        if email:
            msg += f" Account: {email}."
        return AuthStatus(True, msg, account_label=email, method=method)

    # Non-zero: try plain status for older CLIs.
    try:
        plain = _run_claude_auth("auth", "status", timeout=10.0)
        if plain.returncode == 0:
            return AuthStatus(True, "Claude Code subscription linked.", method="subscription")
    except Exception:
        pass

    return AuthStatus(False, _SUBSCRIPTION_HINT, method="subscription")


class ClaudeCodeAuthProvider:
    provider_key = "anthropic"

    def status(self) -> AuthStatus:
        return claude_auth_status()

    def login(self, *, device: bool = False, console: Console | None = None) -> LoginResult:
        from kite.providers.auth.ui import show_byos_panel
        from kite.providers.catalog import load_catalog

        spec = load_catalog().get("claude")
        current = self.status()
        if current.authenticated:
            return LoginResult(0, current.message)

        if claude_cli_path() is None:
            return LoginResult(
                2,
                "Claude Code is not installed. Install the Claude Code CLI, then run: "
                "claude auth login — or configure ANTHROPIC_API_KEY for API billing.",
            )

        show_byos_panel(
            spec,
            url="https://claude.ai",
            console=console,
            browser_opened=None,
            extra="Run Claude Code sign-in. Complete authentication in the browser when prompted.",
        )

        if console is not None:
            console.print("[dim]Starting Claude Code login (`claude auth login`)…[/]")

        try:
            # Official CLI login — no homemade OAuth client.
            proc = _run_claude_auth("auth", "login", timeout=600.0)
        except KeyboardInterrupt:
            return LoginResult(130, "cancelled")
        except subprocess.TimeoutExpired:
            return LoginResult(2, "Claude Code login timed out. Run `claude auth login` manually.")
        except OSError as exc:
            return LoginResult(2, sanitize_auth_message(f"Claude Code login failed: {exc}"))

        if proc.returncode != 0:
            hint = sanitize_auth_message((proc.stderr or proc.stdout or "").strip())
            detail = hint or "Claude Code login did not complete."
            return LoginResult(2, f"{detail} {_SUBSCRIPTION_HINT}")

        after = self.status()
        if not after.authenticated:
            return LoginResult(2, _SUBSCRIPTION_HINT)
        from kite.providers.catalog import load_catalog
        from kite.providers.keys import api_key_for

        key_ready = bool(api_key_for(load_catalog().get("claude")))
        if not key_ready:
            return LoginResult(
                0,
                after.message
                + " Kite model calls still need ANTHROPIC_API_KEY (`kite keys --set anthropic`).",
            )
        return LoginResult(0, after.message)

    def logout(self) -> bool:
        if claude_cli_path() is None:
            return False
        try:
            proc = _run_claude_auth("auth", "logout", timeout=30.0)
            return proc.returncode == 0
        except Exception:
            return False

    def fetch_model_ids(self) -> tuple[str, ...]:
        # Subscription models are not fetched with scraped OAuth tokens — catalog fallback.
        return _FALLBACK_MODELS

    def litellm_env(self) -> dict[str, str]:
        return {}

    def litellm_extras(self) -> dict[str, object]:
        # Never pass Claude Code subscription OAuth tokens as Anthropic API keys.
        return {}


def claude_subscription_ready() -> bool:
    return claude_auth_status().authenticated
