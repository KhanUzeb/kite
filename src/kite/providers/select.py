"""Interactive provider/model selection — shared by CLI and REPL."""

from __future__ import annotations

import sys  # noqa: F401  # re-exported: tests patch kite.providers.select.sys.platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

    from kite.providers.catalog import ProviderSpec


def _current_model(cfg, provider: str) -> str | None:
    return cfg.provider_defaults.get(provider) or (
        cfg.default_model if cfg.default_provider == provider else None
    )


def _can_use_radiolist() -> bool:
    """Thin re-export — canonical logic lives in ``kite.ui.pick``."""
    from kite.ui.pick import can_use_radiolist

    return can_use_radiolist()


def _numbered_pick(
    console: Console,
    items: list[tuple[str, str]],
    *,
    current: str | None,
    title: str,
    noun: str,
    refreshable: bool = False,
) -> str | None:
    """Thin re-export — canonical picker lives in ``kite.ui.pick``."""
    from kite.ui.pick import numbered_pick

    return numbered_pick(
        console,
        items,
        current=current,
        title=title,
        noun=noun,
        refreshable=refreshable,
    )


def _provider_auth_hint(spec: ProviderSpec) -> str:
    """Short auth status for provider pickers."""
    from kite.providers.credentials import inspect_provider_credentials

    return inspect_provider_credentials(spec).detail


def select_model_interactive(
    console: Console,
    provider: str,
    *,
    persist: bool = True,
) -> tuple[int, str | None, str | None]:
    """Interactive picker for live models. Returns (exit_code, provider, model_id)."""
    from kite.config import UserConfig
    from kite.providers.byos import has_oauth_session, is_byok_provider, is_oauth_provider
    from kite.providers.catalog import load_catalog
    from kite.providers.list_models import clear_model_list_cache, list_models_for_provider
    from kite.ui.pick import REFRESH_PICK

    cfg = UserConfig.load()
    catalog = load_catalog()
    try:
        spec = catalog.get(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/]")
        return 2, None, None

    if is_oauth_provider(spec) and not has_oauth_session(spec.oauth_provider or spec.name):
        console.print(
            f"[yellow]{spec.display_name}[/] is not linked. "
            f"Run [cyan]kite login {provider}[/] — a browser opens so you can sign in."
        )
        return 1, None, None

    from kite.providers.credentials import inspect_provider_credentials

    cred = inspect_provider_credentials(spec)
    if not cred.usable:
        if spec.oauth_provider == "anthropic":
            key_hint = "anthropic"
        elif spec.oauth_provider == "antigravity":
            key_hint = "gemini"
        else:
            key_hint = ""
        console.print(
            f"[yellow]{cred.detail}[/]  Run [cyan]kite keys --set {key_hint}[/]"
            if key_hint
            else f"[yellow]{spec.display_name}[/] is not ready for Kite model calls."
        )
        return 1, None, None

    if not is_byok_provider(spec) and not is_oauth_provider(spec):
        console.print(f"[yellow]{spec.display_name}[/] is a flat subscription gateway — no model picker.")
        return 1, None, None

    refresh = False
    while True:
        if refresh:
            clear_model_list_cache(provider)
        console.print(f"[dim]{'Refreshing' if refresh else 'Loading'} models for[/] [bold]{provider}[/]…")
        result = list_models_for_provider(provider, config=cfg, catalog=catalog, refresh=refresh)
        refresh = False
        if result.error:
            console.print(f"[red]{result.error}[/]")
            return 1, None, None
        if not result.models:
            console.print("[red]No models available[/]")
            return 1, None, None

        current = _current_model(cfg, provider)
        values: list[tuple[str, str]] = []
        for m in result.models:
            mark = " *" if current and m.id == current else ""
            ctx = f"ctx {m.context_window}" if m.context_window else ""
            owner = m.owned_by or ""
            meta = " · ".join(p for p in (ctx, owner) if p)
            label = f"{m.id}{mark}" + (f"  ({meta})" if meta else "")
            values.append((m.id, label))

        chosen = _numbered_pick(
            console,
            values,
            current=current,
            title=f"Select a {provider} model",
            noun="model",
            refreshable=True,
        )

        if chosen == REFRESH_PICK:
            refresh = True
            continue
        if not chosen:
            return 130, None, None

        if persist:
            cfg.default_provider = provider
            cfg.default_model = chosen
            cfg.provider_defaults[provider] = chosen
            path = cfg.save()
            console.print(f"[green]Saved[/] {provider}/{chosen}  →  {path}")
        else:
            console.print(
                f"[green]Selected[/] {provider}/{chosen}  [dim](session only — /select save to persist)[/]"
            )

        return 0, provider, chosen


def select_provider_interactive(
    console: Console,
    *,
    byok_only: bool = False,
    oauth_first: bool = False,
) -> str | None:
    """Pick a provider from the catalog. Returns provider name or None."""
    from kite.config import UserConfig
    from kite.config.readiness import RECOMMENDED_PROVIDERS
    from kite.providers.byos import is_byok_provider, is_oauth_provider
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import inspect_provider_credentials

    catalog = load_catalog()
    cfg = UserConfig.load()
    rows = [p for p in catalog.list() if not byok_only or is_byok_provider(p)]

    def _sort_key(spec):
        from kite.ui.pick import provider_sort_key

        return provider_sort_key(
            name=spec.name,
            oauth_first=oauth_first,
            is_oauth=is_oauth_provider(spec),
            ready=inspect_provider_credentials(spec).usable,
            recommended_index=(
                RECOMMENDED_PROVIDERS.index(spec.name) if spec.name in RECOMMENDED_PROVIDERS else 99
            ),
        )

    rows.sort(key=_sort_key)
    values: list[tuple[str, str]] = []
    for spec in rows:
        mark = " *" if spec.name == cfg.default_provider else ""
        auth = _provider_auth_hint(spec)
        note = "recommended" if spec.name in RECOMMENDED_PROVIDERS else ""
        label = f"{spec.display_name}{mark}  ({auth})"
        if note:
            label += f" · {note}"
        values.append((spec.name, label))

    return _numbered_pick(
        console,
        values,
        current=cfg.default_provider,
        title="Select a provider",
        noun="provider",
    )


def connect_interactive(
    console: Console,
    *,
    provider: str | None = None,
    oauth_first: bool = False,
    persist: bool = True,
    login_if_needed: bool = True,
    force_login: bool = False,
) -> tuple[int, str | None, str | None]:
    """Pick provider → login if needed → pick model. One UI path for login/select/provider."""
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import login_provider, provider_needs_login

    if not provider:
        provider = select_provider_interactive(console, oauth_first=oauth_first)
        if not provider:
            return 130, None, None
    try:
        spec = load_catalog().get(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/]")
        return 2, None, None

    if force_login or (login_if_needed and provider_needs_login(spec)):
        code, msg, resolved = login_provider(provider, set_default=persist, console=console)
        if code == 130:
            console.print("[yellow]Cancelled[/]")
            return 130, None, None
        if code != 0:
            console.print(f"[red]{msg}[/]")
            return code, None, None
        console.print(f"[green]{msg}[/]")
        provider = resolved or provider

    return select_model_interactive(console, provider, persist=persist)
