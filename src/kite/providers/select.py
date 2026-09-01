"""Interactive provider/model selection — shared by CLI and REPL."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


def _current_model(cfg, provider: str) -> str | None:
    return cfg.provider_defaults.get(provider) or (
        cfg.default_model if cfg.default_provider == provider else None
    )


def _radiolist_pick(title: str, values: list[tuple[str, str]]) -> str | None:
    """Arrow-key picker when prompt_toolkit is available."""
    try:
        from prompt_toolkit.shortcuts import radiolist_dialog

        return radiolist_dialog(title=title, text="↑↓ move · Enter select · Esc cancel", values=values).run()
    except Exception:
        return None


def _numbered_pick(console: Console, models: list, current: str | None) -> str | None:
    from rich.table import Table

    table = Table(title="Select a model")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("model")
    table.add_column("context")
    table.add_column("owned_by")
    for i, m in enumerate(models, start=1):
        mark = " *" if current and m.id == current else ""
        ctx = str(m.context_window) if m.context_window else "—"
        table.add_row(str(i), m.id + mark, ctx, m.owned_by or "—")
    console.print(table)
    console.print("[dim]* = currently selected · Enter number or model id · empty = cancel[/]")

    try:
        raw = console.input("Pick model: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled[/]")
        return None

    if not raw:
        console.print("[yellow]Cancelled[/]")
        return None

    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(models):
            return models[idx - 1].id
        return None
    ids = {m.id for m in models}
    if raw in ids:
        return raw
    hits = [m.id for m in models if raw.lower() in m.id.lower()]
    return hits[0] if len(hits) == 1 else None


def select_model_interactive(
    console: Console,
    provider: str,
    *,
    persist: bool = True,
) -> tuple[int, str | None, str | None]:
    """Interactive picker for BYOK live models. Returns (exit_code, provider, model_id)."""
    from kite.config import UserConfig
    from kite.providers.byos import is_byok_provider, is_oauth_provider
    from kite.providers.catalog import load_catalog
    from kite.providers.list_models import list_models_for_provider
    from kite.util.tty import is_interactive_tty

    cfg = UserConfig.load()
    catalog = load_catalog()
    try:
        spec = catalog.get(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/]")
        return 2, None, None

    if is_oauth_provider(spec):
        console.print(
            f"[yellow]{spec.display_name}[/] uses subscription OAuth — no API model picker."
        )
        console.print(
            f"Run [cyan]kite login {provider}[/] to link your plan. "
            f"Models are fetched live from your subscription after login."
        )
        if spec.default_model:
            console.print(f"[dim]Catalog default:[/] {spec.default_model}")
            if persist:
                cfg.default_provider = provider
                cfg.default_model = spec.default_model
                cfg.provider_defaults[provider] = spec.default_model
                path = cfg.save()
                console.print(f"[green]Saved default[/] {provider}/{spec.default_model}  →  {path}")
                return 0, provider, spec.default_model
        return 1, provider, spec.default_model or None

    if not is_byok_provider(spec):
        console.print(f"[yellow]{spec.display_name}[/] is a flat subscription gateway — no model picker.")
        return 1, None, None

    console.print(f"[dim]Fetching models for[/] [bold]{provider}[/]…")
    result = list_models_for_provider(provider, config=cfg, catalog=catalog)
    if result.error:
        console.print(f"[red]{result.error}[/]")
        return 1, None, None
    if not result.models:
        console.print("[red]No models available[/]")
        return 1, None, None

    current = _current_model(cfg, provider)
    chosen: str | None = None

    if is_interactive_tty():
        values: list[tuple[str, str]] = []
        for m in result.models:
            mark = " *" if current and m.id == current else ""
            ctx = f"ctx {m.context_window}" if m.context_window else ""
            owner = m.owned_by or ""
            meta = " · ".join(p for p in (ctx, owner) if p)
            label = f"{m.id}{mark}" + (f"  ({meta})" if meta else "")
            values.append((m.id, label))
        chosen = _radiolist_pick(f"Select a {provider} model", values)

    if chosen is None:
        chosen = _numbered_pick(console, list(result.models), current)

    if not chosen:
        console.print("[red]Invalid selection[/]")
        return 2, None, None

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


def select_provider_interactive(console: Console, *, byok_only: bool = False) -> str | None:
    """Pick a provider from the catalog. Returns provider name or None."""
    from kite.config import UserConfig
    from kite.config.readiness import RECOMMENDED_PROVIDERS
    from kite.providers.byos import is_byok_provider
    from kite.providers.catalog import load_catalog
    from kite.providers.keys import api_key_for
    from kite.util.tty import is_interactive_tty

    catalog = load_catalog()
    cfg = UserConfig.load()
    rows = [p for p in catalog.list() if not byok_only or is_byok_provider(p)]

    def _sort_key(spec):
        name = spec.name
        has_key = name == "ollama" or bool(api_key_for(spec))
        rec = RECOMMENDED_PROVIDERS.index(name) if name in RECOMMENDED_PROVIDERS else 99
        return (0 if has_key else 1, rec, name)

    rows.sort(key=_sort_key)

    if is_interactive_tty():
        values: list[tuple[str, str]] = []
        for spec in rows:
            mark = " *" if spec.name == cfg.default_provider else ""
            if spec.name == "ollama":
                key = "local"
            elif spec.api_key_env:
                key = "key set" if api_key_for(spec) else "missing key"
            else:
                key = "oauth/sub"
            note = "recommended" if spec.name in RECOMMENDED_PROVIDERS else ""
            label = f"{spec.name}{mark}  ({key})" + (f" · {note}" if note else "")
            values.append((spec.name, label))
        picked = _radiolist_pick("Select a provider", values)
        if picked:
            return picked

    from rich.table import Table

    table = Table(title="Select a provider")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("name")
    table.add_column("key")
    table.add_column("env var")
    table.add_column("note")
    for i, spec in enumerate(rows, start=1):
        mark = " *" if spec.name == cfg.default_provider else ""
        if spec.name == "ollama":
            key = "local"
        elif spec.api_key_env:
            key = "yes" if api_key_for(spec) else "missing"
        else:
            key = "—"
        env = spec.api_key_env or "—"
        note = "recommended" if spec.name in RECOMMENDED_PROVIDERS else ""
        table.add_row(str(i), spec.name + mark, key, env, note)
    console.print(table)
    console.print("[dim]* = default · keys and recommended providers listed first[/]")

    try:
        raw = console.input("Pick provider (number or name): ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled[/]")
        return None

    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(rows):
            return rows[idx - 1].name
        return None
    try:
        return catalog.get(raw).name
    except KeyError:
        hits = [p.name for p in rows if raw.lower() in p.name.lower()]
        return hits[0] if len(hits) == 1 else None
