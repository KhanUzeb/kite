"""Google Antigravity subscription auth — delegated to the official `agy` CLI.

Official method only (https://antigravity.google/docs/cli/install/):
- Sign-in happens by launching `agy` itself: silent OS-keyring session on
  local machines, automatic browser flow when needed, manual URL loop over
  SSH. There is no `agy login` subcommand — bare `agy` IS the sign-in.
- Logout is `/logout` inside the agy prompt box (purges the keyring
  session, per "Managing your session" in the official docs).
- There is no `agy status` subcommand either, so Kite verifies a session
  with the documented read-only `agy models` probe instead of trusting
  process exit codes (quitting the agy TUI exits 0 without signing in).

Kite never holds Google tokens — only a linkage marker. Subscription turns
run through the signed-in `agy` CLI (`agy -p --mode plan`, text-only);
GEMINI_API_KEY (`kite keys --set gemini`) upgrades to direct LiteLLM calls
with tool support for agent runs.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from kite.guardrails.redact import redact_string
from kite.providers.auth.base import AuthStatus, LoginResult, sanitize_auth_message

if TYPE_CHECKING:
    from rich.console import Console

_AGY_BIN = "agy"
# Unauthenticated fallback only — the live list comes from `agy models`.
_FALLBACK_MODELS = (
    "gemini-3.8-flash-medium",
    "gemini-3.7-flash-medium",
    "gemini-3.1-pro-high",
    "claude-sonnet-4-6",
)
_INSTALL_HINT = (
    "Antigravity CLI is not installed. Install it from "
    "https://antigravity.google/docs/cli/install/ "
    "or configure GEMINI_API_KEY for API access."
)
_KEYRING_HINT = (
    "If sign-in hangs or reports a locked keyring, unlock your OS keyring "
    "(Windows Credential Manager / macOS Keychain / Linux Secret Service) — "
    "see https://antigravity.google/docs/cli/troubleshooting/."
)
# Only these hosts are ever treated as sign-in URLs. The old first-URL-wins
# regex surfaced docs/telemetry/update links as "sign in here".
_AUTH_URL_HOSTS = ("accounts.google.com", "antigravity.google", "127.0.0.1", "localhost")
_PROBE_TIMEOUT = 30.0
# A verified marker skips the (slow, network) `agy models` probe so status
# checks during normal runs stay subprocess-free.
_VERIFY_TTL_SECONDS = 24 * 3600.0


def agy_cli_path() -> str | None:
    return shutil.which(_AGY_BIN)


def _link_marker() -> object:
    from kite.providers.byos import oauth_auth_file

    return oauth_auth_file("antigravity")


def _read_marker() -> dict:
    import json

    try:
        path = _link_marker()  # type: ignore[assignment]
        if not (path.is_file() and path.stat().st_size > 2):
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _verification_fresh(payload: dict) -> bool:
    import time

    try:
        verified_at = float(payload.get("verified_at", 0.0))
    except (TypeError, ValueError):
        return False
    return (time.time() - verified_at) < _VERIFY_TTL_SECONDS


def _mark_linked(account_label: str = "", *, models: tuple[str, ...] = ()) -> None:
    import time

    from kite.providers.auth.base import atomic_write_json

    payload: dict[str, object] = {
        "linked": True,
        "linked_at": time.time(),
        "verified_at": time.time(),
        "verified_via": "agy models",
    }
    if account_label:
        payload["account_label"] = account_label
    if models:
        payload["models"] = list(models)
    atomic_write_json(_link_marker(), payload)  # type: ignore[arg-type]


def probe_session(
    *,
    timeout: float = _PROBE_TIMEOUT,
    on_error: Callable[[str], None] | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Verify the agy keyring session via the documented `agy models` probe.

    Returns (ok, model_ids). Read-only: lists models, burns no credits.
    """
    from kite.providers.auth.cli import run_cli

    def fail(reason: str) -> tuple[bool, tuple[str, ...]]:
        if on_error is not None:
            on_error(redact_string(reason))
        return False, ()

    if agy_cli_path() is None:
        return fail("agy CLI is not installed.")
    try:
        proc = run_cli(_AGY_BIN, "models", timeout=timeout)
    except subprocess.TimeoutExpired:
        return fail(f"agy models verification timed out after {timeout:g} seconds.")
    except OSError as exc:
        return fail(f"could not run agy models verification: {exc}")
    if proc.returncode != 0:
        detail = redact_string((proc.stdout or "").strip())
        reason = detail or f"agy models exited with status {proc.returncode}."
        return fail(reason)
    models: list[str] = []
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("fetching"):
            continue
        first = stripped.split()[0]
        if first.startswith("gemini-") or first.startswith("claude-") or first.startswith("gpt-"):
            models.append(first)
        elif "-" in first and " " not in first:
            models.append(first)
    if not models:
        return fail("agy models returned no model IDs.")
    return True, tuple(models)


def _auth_url_in_line(line: str) -> str:
    """Extract a sign-in URL from a line, or '' if none is present."""
    import re
    from urllib.parse import urlsplit

    for match in re.finditer(r"https://[^\s]+", line):
        url = match.group(0).rstrip(".,)'\"")
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            continue
        if host == "localhost" or host in _AUTH_URL_HOSTS or host.endswith(".google.com"):
            return url
    return ""


class AntigravityAuthProvider:
    provider_key = "antigravity"

    def status(self) -> AuthStatus:
        if agy_cli_path() is None:
            return AuthStatus(False, _INSTALL_HINT, method="subscription")
        payload = _read_marker()
        if payload.get("linked") and _verification_fresh(payload):
            return AuthStatus(True, "Antigravity subscription linked.", method="subscription")
        failures: list[str] = []
        ok, _models = probe_session(on_error=failures.append)
        if ok:
            _mark_linked()
            return AuthStatus(True, "Antigravity subscription linked.", method="subscription")
        if failures:
            # Keep a stale positive marker so a transient verification outage
            # cannot erase evidence of an existing, previously verified link.
            message = (
                f"Antigravity link verification failed: {failures[0]} "
                "Check the connection/provider status and retry. If you are not signed in, "
                "run `kite login antigravity`."
            )
        else:
            message = "Antigravity is not linked. Run: kite login antigravity (or sign in via agy)."
        return AuthStatus(False, message, method="subscription")

    def login(self, *, device: bool = False, console: Console | None = None) -> LoginResult:
        from kite.providers.auth.ui import open_browser, show_byos_panel
        from kite.providers.catalog import load_catalog
        from kite.util.tty import is_interactive_tty

        spec = load_catalog().get("antigravity")

        if agy_cli_path() is None:
            return LoginResult(2, _INSTALL_HINT)

        if self.status().authenticated:
            return LoginResult(0, "Antigravity subscription already linked.")

        interactive = is_interactive_tty(require_stdout=False)

        if interactive and not device:
            # Official flow, natively: agy owns the keyring/browser/SSH-loop
            # UI. Kite hands over the terminal instead of piping agy's TUI
            # through a captured stream (which garbles it and hides input).
            show_byos_panel(
                spec,
                url="https://antigravity.google/docs/cli/install/",
                console=console,
                browser_opened=None,
                extra="Starting Antigravity sign-in (finish in the agy session)…",
            )
            try:
                subprocess.run([_AGY_BIN], timeout=600.0, check=False)
            except KeyboardInterrupt:
                return LoginResult(130, "cancelled")
            except subprocess.TimeoutExpired:
                return LoginResult(2, "Antigravity sign-in timed out. Run `agy` manually.")
            except OSError as exc:
                return LoginResult(2, sanitize_auth_message(f"Antigravity login failed: {exc}"))
        else:
            # Headless/SSH: stream agy's output so Kite can surface the
            # manual-loop sign-in URL the moment it appears.
            login_timeout = 600.0 if interactive else 120.0
            seen: dict[str, object] = {"url": "", "opened": False}

            def _on_line(line: str) -> None:
                if seen["url"]:
                    return
                url = _auth_url_in_line(line)
                if not url:
                    return
                seen["url"] = url
                # agy opens the browser itself on local TTYs; Kite opens the
                # URL only where agy cannot (headless/SSH manual loop).
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

            show_byos_panel(
                spec,
                url="https://antigravity.google/docs/cli/install/",
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
                proc = run_cli_streaming(_AGY_BIN, timeout=login_timeout, on_line=_on_line)
            except KeyboardInterrupt:
                return LoginResult(130, "cancelled")
            except subprocess.TimeoutExpired:
                return LoginResult(2, "Antigravity login timed out. Run `agy` manually.")
            except OSError as exc:
                return LoginResult(2, sanitize_auth_message(f"Antigravity login failed: {exc}"))

            if proc.returncode != 0:
                detail = sanitize_auth_message((proc.stdout or "").strip())
                return LoginResult(2, detail or f"Antigravity login failed. {_KEYRING_HINT}")

        # Never trust the exit code: quitting agy without signing in still
        # exits 0. Verify the keyring session with the read-only probe.
        failures: list[str] = []
        ok, models = probe_session(on_error=failures.append)
        if not ok:
            if failures:
                return LoginResult(
                    2,
                    f"Antigravity sign-in verification failed: {failures[0]} "
                    f"Check connection/provider status, then retry `kite login antigravity`. {_KEYRING_HINT}",
                )
            return LoginResult(
                2,
                "Antigravity sign-in did not complete (no valid session found). "
                f"Run `agy` and finish Google sign-in, then retry. {_KEYRING_HINT}",
            )
        _mark_linked(models=models)
        return LoginResult(
            0,
            f"Antigravity subscription linked ({len(models)} models available). "
            "Chat runs through your signed-in agy CLI; `kite keys --set gemini` "
            "adds tool-driven agent runs.",
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
        payload = _read_marker()
        if payload.get("linked"):
            cached = payload.get("models")
            if isinstance(cached, list) and cached and all(isinstance(m, str) for m in cached):
                return tuple(cached)
            ok, models = probe_session()
            if ok:
                return models
        elif agy_cli_path() is not None:
            ok, models = probe_session()
            if ok:
                return models
        # No undocumented model API from Kite — static fallback.
        return _FALLBACK_MODELS

    def litellm_env(self) -> dict[str, str]:
        return {}

    def litellm_extras(self) -> dict[str, object]:
        # Never pass Antigravity subscription OAuth tokens as API keys.
        return {}
