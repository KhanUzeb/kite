"""Google Antigravity subscription auth — delegated to the official `agy` CLI.

`agy` owns the Google OAuth session (browser flow locally, manual URL loop
over SSH; tokens stay in the OS keyring). Kite only records a linkage
marker — never tokens. Kite model calls still need GEMINI_API_KEY
(`kite keys --set gemini`); the subscription itself is CLI-owned, same as
the Claude Code pattern.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from kite.providers.auth.base import AuthStatus, LoginResult, sanitize_auth_message
from kite.providers.auth.cli import run_cli

if TYPE_CHECKING:
    from rich.console import Console

_AGY_BIN = "agy"
_FALLBACK_MODELS = ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash")
_INSTALL_HINT = (
    "Antigravity CLI is not installed. Install it from "
    "https://antigravity.google/docs/cli/install/ "
    "or configure GEMINI_API_KEY for API access."
)


def agy_cli_path() -> str | None:
    return shutil.which(_AGY_BIN)


def _link_marker() -> object:
    from kite.providers.byos import oauth_auth_file

    return oauth_auth_file("antigravity")


def _link_marked() -> bool:
    try:
        path = _link_marker()  # type: ignore[assignment]
        return path.is_file() and path.stat().st_size > 2
    except OSError:
        return False


def _mark_linked(account_label: str = "") -> None:
    import time

    from kite.providers.auth.base import atomic_write_json

    payload = {"linked": True, "linked_at": time.time()}
    if account_label:
        payload["account_label"] = account_label
    atomic_write_json(_link_marker(), payload)  # type: ignore[arg-type]


class AntigravityAuthProvider:
    provider_key = "antigravity"

    def status(self) -> AuthStatus:
        if agy_cli_path() is None:
            return AuthStatus(False, _INSTALL_HINT, method="subscription")
        if _link_marked():
            return AuthStatus(True, "Antigravity subscription linked.", method="subscription")
        return AuthStatus(
            False,
            "Antigravity is not linked. Run: kite login antigravity (or sign in via agy).",
            method="subscription",
        )

    def login(self, *, device: bool = False, console: Console | None = None) -> LoginResult:
        import re

        from kite.providers.auth.ui import open_browser, show_byos_panel
        from kite.providers.catalog import load_catalog
        from kite.util.tty import is_interactive_tty

        spec = load_catalog().get("antigravity")

        if agy_cli_path() is None:
            return LoginResult(2, _INSTALL_HINT)

        if self.status().authenticated:
            return LoginResult(0, "Antigravity subscription already linked.")

        interactive = is_interactive_tty(require_stdout=False)
        # `agy` drives its own sign-in (keyring session, browser, or the SSH
        # manual URL loop). Stream its output so Kite can surface the
        # sign-in URL the moment it appears instead of hiding it until exit.
        cmd = [_AGY_BIN]

        login_timeout = 600.0 if interactive else 120.0
        seen: dict[str, object] = {"url": "", "opened": False}

        def _on_line(line: str) -> None:
            if seen["url"]:
                return
            match = re.search(r"https://[^\s]+", line)
            if not match:
                return
            url = match.group(0).rstrip(".,)'\"")
            seen["url"] = url
            # agy opens the browser itself on local TTYs; Kite opens the URL
            # only where agy cannot (headless/SSH manual loop).
            if not interactive or device:
                seen["opened"] = open_browser(url)
            show_byos_panel(
                spec,
                url=url,
                console=console,
                browser_opened=bool(seen["opened"]) if not interactive else None,
                extra=(
                    "Opened your browser — finish Google sign-in there."
                    if seen["opened"]
                    else "Open this URL to sign in with Google."
                ),
            )

        if interactive:
            show_byos_panel(
                spec,
                url="https://antigravity.google",
                console=console,
                browser_opened=None,
                extra="Starting Antigravity sign-in…",
            )
        wait_msg = "Waiting for Google sign-in…"
        if console is not None:
            console.print(f"[dim]{wait_msg}[/]")
        else:
            print(wait_msg, flush=True)

        from kite.providers.auth.cli import run_cli_streaming

        try:
            proc = run_cli_streaming(*cmd, timeout=login_timeout, on_line=_on_line)
        except KeyboardInterrupt:
            return LoginResult(130, "cancelled")
        except subprocess.TimeoutExpired:
            return LoginResult(2, "Antigravity login timed out. Run `agy` manually.")
        except OSError as exc:
            return LoginResult(2, sanitize_auth_message(f"Antigravity login failed: {exc}"))

        if proc.returncode != 0:
            detail = sanitize_auth_message((proc.stdout or "").strip())
            return LoginResult(2, detail or "Antigravity login failed.")

        _mark_linked()
        return LoginResult(
            0,
            "Antigravity subscription linked. "
            "Kite model calls still need GEMINI_API_KEY (`kite keys --set gemini`).",
        )

    def logout(self) -> bool:
        try:
            path = _link_marker()  # type: ignore[assignment]
        except OSError:
            return False
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True

    def fetch_model_ids(self) -> tuple[str, ...]:
        if not self.status().authenticated:
            return _FALLBACK_MODELS
        # No undocumented model API from Kite — static fallback.
        return _FALLBACK_MODELS

    def litellm_env(self) -> dict[str, str]:
        return {}

    def litellm_extras(self) -> dict[str, object]:
        # Never pass Antigravity subscription OAuth tokens as API keys.
        return {}
