"""First-run / setup readiness — shared by CLI, REPL, and install scripts."""

from __future__ import annotations

import os
from dataclasses import dataclass

from kite.config import UserConfig, kite_home
from kite.providers.credentials import configured_providers
from kite.providers.resolve import missing_credentials, missing_model, resolve_model

# Shown in setup wizard and fresh-install hints (free tiers / local).
RECOMMENDED_PROVIDERS: tuple[str, ...] = ("groq", "openrouter", "ollama")


@dataclass(frozen=True)
class SetupStatus:
    ready: bool
    has_config_file: bool
    has_any_api_key: bool
    configured_providers: tuple[str, ...]
    default_provider: str
    default_model: str | None
    blockers: tuple[str, ...]
    hints: tuple[str, ...]


def config_path() -> str:
    return str(kite_home() / "config.toml")


def has_config_file() -> bool:
    return (kite_home() / "config.toml").is_file()


def configured_provider_names() -> tuple[str, ...]:
    return tuple(name for name, ok, _ in configured_providers() if ok)


def has_any_api_key() -> bool:
    return any(name != "ollama" for name in configured_provider_names())


def is_fresh_install() -> bool:
    """No saved config and no cloud API keys yet."""
    if has_config_file():
        return False
    return not has_any_api_key()


def assess_setup_status(
    *,
    provider: str | None = None,
    model: str | None = None,
    config: UserConfig | None = None,
) -> SetupStatus:
    cfg = config or UserConfig.load()
    ready_names = configured_provider_names()
    resolved = resolve_model(provider=provider, model=model, config=cfg)
    blockers: list[str] = []
    hints: list[str] = []

    cred = missing_credentials(resolved)
    if cred:
        blockers.append(cred)
    model_gap = missing_model(resolved)
    if model_gap:
        blockers.append(model_gap)

    if not blockers:
        return SetupStatus(
            ready=True,
            has_config_file=has_config_file(),
            has_any_api_key=has_any_api_key(),
            configured_providers=ready_names,
            default_provider=resolved.provider,
            default_model=resolved.model or None,
            blockers=(),
            hints=(),
        )

    if ready_names:
        others = [n for n in ready_names if n != resolved.provider]
        if others:
            hints.append(f"Keys ready for: {', '.join(others)} — run /model select or kite setup")
    elif is_fresh_install():
        hints.append("Free tier: groq.com → /login groq  ·  Local: ollama → /model ollama/<id>")
        hints.append("Run kite setup or /setup for the guided wizard")

    if not has_config_file():
        hints.append(f"Config not saved yet — setup writes {config_path()}")

    return SetupStatus(
        ready=False,
        has_config_file=has_config_file(),
        has_any_api_key=has_any_api_key(),
        configured_providers=ready_names,
        default_provider=resolved.provider,
        default_model=resolved.model or None,
        blockers=tuple(blockers),
        hints=tuple(hints),
    )


def needs_setup(
    *,
    provider: str | None = None,
    model: str | None = None,
    config: UserConfig | None = None,
) -> bool:
    return not assess_setup_status(provider=provider, model=model, config=config).ready


def format_setup_banner(status: SetupStatus) -> str:
    if status.ready:
        return ""
    lines = ["[kite.pending]Setup needed[/] — Kite cannot run tasks yet."]
    for b in status.blockers[:2]:
        lines.append(f"  [kite.muted]{b}[/]")
    for h in status.hints[:3]:
        lines.append(f"  [kite.brand]{h}[/]")
    lines.append("  [kite.muted]Fix:[/] [kite.brand]/setup[/]  or  [kite.brand]kite setup[/]  ·  [kite.brand]/login groq[/]")
    return "\n".join(lines)


def offer_setup_interactive(console) -> bool:
    """Ask on a TTY whether to run setup now. Returns True if user wants setup."""
    if os.environ.get("KITE_SKIP_SETUP"):
        return False
    if not (os.stdin.isatty() and os.stdout.isatty()):
        return False
    if not is_fresh_install():
        return False
    try:
        raw = console.input("[kite.brand]First run?[/] Run [cyan]kite setup[/] now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
    return raw in ("", "y", "yes")
