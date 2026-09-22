"""xAI Grok subscription auth — delegated to the official grok CLI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from kite.providers.auth.base import AuthStatus, LoginResult, sanitize_auth_message
from kite.providers.auth.cli import run_cli

if TYPE_CHECKING:
    from rich.console import Console

_GROK_BIN = "grok"
_FALLBACK_MODELS = ("grok-4.6", "grok-4", "grok-3")


def grok_cli_path() -> str | None:
    return shutil.which(_GROK_BIN)


def grok_home() -> Path:
    import os

    override = os.environ.get("GROK_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".grok"


def grok_auth_file() -> Path:
    return grok_home() / "auth.json"


def _grok_auth_present() -> bool:
    """Best-effort check that Grok runtime has cached credentials (no token parsing)."""
    path = grok_auth_file()
    return path.is_file() and path.stat().st_size > 2


class GrokCliAuthProvider:
    provider_key = "xai"

    def status(self) -> AuthStatus:
        if grok_cli_path() is None:
            return AuthStatus(
                False,
                "Grok CLI is not installed. Install from https://docs.x.ai/build/overview "
                "or use XAI_API_KEY (kite keys --set xai).",
                method="subscription",
            )
        if _grok_auth_present():
            return AuthStatus(True, "Grok subscription linked.", method="subscription")
        return AuthStatus(
            False,
            "Grok is not authenticated. Run: kite login grok (or grok login).",
            method="subscription",
        )

    def login(self, *, device: bool = False, console: Console | None = None) -> LoginResult:
        import re

        from kite.providers.auth.ui import open_browser, show_byos_panel
        from kite.providers.catalog import load_catalog
        from kite.util.tty import is_interactive_tty

        spec = load_catalog().get("grok")

        if grok_cli_path() is None:
            return LoginResult(
                2,
                "Grok CLI is not installed. Install it from https://docs.x.ai/build/overview "
                "or configure XAI_API_KEY for API access.",
            )

        if self.status().authenticated:
            return LoginResult(0, "Grok subscription already linked.")

        interactive = is_interactive_tty(require_stdout=False)
        use_device = device or not interactive
        # Interactive TTYs use the default browser OAuth flow (`--oauth`);
        # headless / --device uses the device-code flow (no localhost callback).
        # Stream the CLI output so Kite can open the printed sign-in URL
        # immediately instead of hiding it until the child exits.
        cmd = [_GROK_BIN, "login", "--device-auth" if use_device else "--oauth"]

        login_timeout = 600.0 if interactive else 30.0
        seen: dict[str, object] = {"url": "", "code": "", "opened": False}

        def _on_line(line: str) -> None:
            if seen["url"]:
                return
            match = re.search(r"https://[^\s]+", line)
            if not match:
                return
            url = match.group(0).rstrip(".,)'\"")
            seen["url"] = url
            code_match = re.search(r"user_code=([A-Za-z0-9-]+)", url) or re.search(
                r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", line
            )
            if code_match:
                seen["code"] = code_match.group(1)
            if interactive:
                seen["opened"] = open_browser(url)
            show_byos_panel(
                spec,
                url=url,
                console=console,
                user_code=str(seen["code"] or ""),
                browser_opened=bool(seen["opened"]) if interactive else None,
                extra=(
                    "Opened your browser — finish sign-in there."
                    if seen["opened"]
                    else "Open this URL to sign in."
                ),
            )

        if interactive:
            show_byos_panel(
                spec,
                url="https://auth.x.ai",
                console=console,
                browser_opened=None,
                extra="Starting xAI sign-in…",
            )
        wait_msg = "Waiting for xAI sign-in…"
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
            return LoginResult(2, "Grok login timed out. Run `grok login` manually.")
        except OSError as exc:
            return LoginResult(2, sanitize_auth_message(f"Grok login failed: {exc}"))

        if proc.returncode != 0:
            detail = sanitize_auth_message((proc.stdout or "").strip())
            return LoginResult(2, detail or "Grok login failed.")

        if not _grok_auth_present():
            return LoginResult(2, "Grok login did not complete — no session found.")
        return LoginResult(0, "Grok subscription linked.")

    def logout(self) -> bool:
        if grok_cli_path() is None:
            return False
        removed = False
        try:
            proc = run_cli(_GROK_BIN, "logout", timeout=30.0)
            if proc.returncode == 0:
                removed = True
        except Exception:
            pass
        auth = grok_auth_file()
        if auth.is_file():
            try:
                auth.unlink()
                removed = True
            except OSError:
                pass
        return removed

    def fetch_model_ids(self) -> tuple[str, ...]:
        if not self.status().authenticated:
            return _FALLBACK_MODELS
        # No undocumented model API from Kite — static fallback when CLI cannot list models.
        return _FALLBACK_MODELS

    def litellm_env(self) -> dict[str, str]:
        # Grok CLI nests tokens under an issuer URL; LiteLLM needs a flat
        # auth.json. Bridge into ~/.kite/oauth/xai (see grok_litellm).
        from kite.providers.auth.grok_litellm import litellm_xai_env

        return litellm_xai_env()

    def litellm_extras(self) -> dict[str, object]:
        return {"use_xai_oauth": True}
