"""Durable first-run / setup-auto-prompt state (~/.kite/onboarding.complete)."""

from __future__ import annotations

from pathlib import Path

from kite.config.user import ensure_home, kite_home

MARKER_NAME = "onboarding.complete"


def onboarding_marker_path() -> Path:
    return kite_home() / MARKER_NAME


def onboarding_marker_exists() -> bool:
    return onboarding_marker_path().is_file()


def mark_setup_complete() -> Path:
    """Record that onboarding auto-prompt should not run again."""
    ensure_home()
    path = onboarding_marker_path()
    if not path.is_file():
        path.write_text("completed\n", encoding="utf-8")
    return path


def any_provider_connection() -> bool:
    """True if any LLM provider has a stored key or BYOS subscription session."""
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import inspect_provider_credentials, load_kite_env

    load_kite_env()
    for spec in load_catalog().list():
        if spec.name == "ollama":
            continue
        cred = inspect_provider_credentials(spec)
        if cred.linked:
            return True
    return False


def is_setup_complete() -> bool:
    """Setup auto-prompt is done: marker, or any provider credentials linked."""
    if onboarding_marker_exists():
        return True
    return any_provider_connection()


def should_auto_prompt_setup() -> bool:
    """True only for a genuine fresh install (no credentials, no marker)."""
    return not is_setup_complete()
