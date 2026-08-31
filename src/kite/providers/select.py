"""Interactive provider/model selection — shared by CLI and REPL."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


def select_model_interactive(
    console: Console,
    provider: str,
    *,
    persist: bool = True,
) -> tuple[int, str | None, str | None]:
    """Numbered picker for live models. Returns (exit_code, provider, model_id)."""
    from rich.table import Table

    from kite.config import UserConfig
    from kite.providers.catalog import load_catalog
    from kite.providers.list_models import list_models_for_provider

    cfg = UserConfig.load()
    catalog = load_catalog()
    try:
        catalog.get(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/]")
        return 2, None, None

    console.print(f"[dim]Fetching models for[/] [bold]{provider}[/]…")
    result = list_models_for_provider(provider, config=cfg, catalog=catalog)
    if result.error:
        console.print(f"[red]{result.error}[/]")
        return 1, None, None
    if not result.models:
        console.print("[red]No models available[/]")
        return 1, None, None

    table = Table(title=f"Select a {provider} model")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("model")
    table.add_column("context")
    table.add_column("owned_by")
    current = cfg.provider_defaults.get(provider) or (
        cfg.default_model if cfg.default_provider == provider else None
    )
    for i, m in enumerate(result.models, start=1):
        mark = " *" if current and m.id == current else ""
        ctx = str(m.context_window) if m.context_window else "—"
        table.add_row(str(i), m.id + mark, ctx, m.owned_by or "—")
    console.print(table)
    console.print("[dim]* = currently selected · Enter number or model id · empty = cancel[/]")

    try:
        raw = console.input("Pick model: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled[/]")
        return 130, None, None

    if not raw:
        console.print("[yellow]Cancelled[/]")
        return 130, None, None

    chosen: str | None = None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(result.models):
            chosen = result.models[idx - 1].id
    else:
        ids = {m.id for m in result.models}
        if raw in ids:
            chosen = raw
        else:
            hits = [m.id for m in result.models if raw.lower() in m.id.lower()]
            if len(hits) == 1:
                chosen = hits[0]

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
        console.print(f"[green]Selected[/] {provider}/{chosen}  [dim](session only — /select save to persist)[/]")

    return 0, provider, chosen


def select_provider_interactive(console: Console) -> str | None:
    """Pick a provider from the catalog. Returns provider name or None."""
    from rich.table import Table

    from kite.config import UserConfig
    from kite.config.readiness import RECOMMENDED_PROVIDERS
    from kite.providers.catalog import load_catalog
    from kite.providers.keys import api_key_env_names, api_key_for

    catalog = load_catalog()
    cfg = UserConfig.load()
    rows = list(catalog.list())

    def _sort_key(spec):
        name = spec.name
        has_key = name == "ollama" or bool(api_key_for(spec))
        rec = RECOMMENDED_PROVIDERS.index(name) if name in RECOMMENDED_PROVIDERS else 99
        return (0 if has_key else 1, rec, name)

    rows.sort(key=_sort_key)

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
        note = ""
        if spec.name in RECOMMENDED_PROVIDERS:
            note = "recommended"
        if spec.name in RECOMMENDED_PROVIDERS and key == "missing":
            note = "free tier" if spec.name != "ollama" else "local"
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
