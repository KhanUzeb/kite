"""BYOK/BYOS credential UI — shared panels and tables for CLI + REPL."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from kite.ui.style import GUTTER, SYMBOL_OK, SYMBOL_WARN

if TYPE_CHECKING:
    from kite.providers.catalog import ProviderSpec


def render_byok_login_panel(
    spec: ProviderSpec,
    *,
    env_path: str,
    env_var: str,
    replacing: bool = False,
) -> Text:
    """Left-bar login panel for BYOK API key entry."""
    body = Text()
    body.append(f"{GUTTER}┊ ", style="kite.pending")
    body.append("BYOK login", style="kite.pending bold")
    body.append(f"  ·  {spec.display_name}\n", style="kite.muted")
    body.append(f"{GUTTER}┊ ", style="kite.muted")
    body.append("Your API key stays on this machine in ", style="kite.muted")
    body.append(env_path, style="cyan")
    body.append(" (owner-only).\n", style="kite.muted")
    body.append(f"{GUTTER}┊ ", style="kite.muted")
    body.append("Saved as ", style="kite.muted")
    body.append(env_var, style="bold")
    body.append(" — never echoed or logged.\n", style="kite.muted")
    if spec.docs_url:
        body.append(f"{GUTTER}┊ ", style="kite.muted")
        body.append(f"Get a key: {spec.docs_url}\n", style="kite.muted")
    if replacing:
        body.append(f"{GUTTER}┊ ", style="kite.pending")
        body.append(f"{SYMBOL_WARN} ", style="kite.pending")
        body.append("Replacing an existing key for this provider.\n", style="kite.pending")
    body.append(f"{GUTTER}┊\n", style="kite.muted")
    body.append(f"{GUTTER}┊ ", style="kite.muted")
    body.append("Enter key (hidden). New keys are entered twice to avoid typos.\n", style="kite.muted")
    return body


def render_byos_login_panel(
    spec: ProviderSpec,
    *,
    url: str,
    user_code: str = "",
    browser_opened: bool | None = False,
    extra: str = "",
) -> Text:
    """Left-bar login panel for subscription OAuth (browser + optional device code)."""
    body = Text()
    body.append(f"{GUTTER}┊ ", style="kite.pending")
    body.append("BYOS login", style="kite.pending bold")
    body.append(f"  ·  {spec.display_name}\n", style="kite.muted")
    body.append(f"{GUTTER}┊ ", style="kite.muted")
    body.append("Uses your subscription plan — not API credits.\n", style="kite.muted")
    if browser_opened is True:
        body.append(f"{GUTTER}┊ ", style="kite.success")
        body.append(f"{SYMBOL_OK} ", style="kite.success")
        body.append("Opened your browser. Sign in there.\n", style="kite.success")
    elif browser_opened is None:
        body.append(f"{GUTTER}┊ ", style="kite.pending")
        body.append("A browser window will open. Sign in there.\n", style="kite.pending")
    else:
        body.append(f"{GUTTER}┊ ", style="kite.pending")
        body.append(f"{SYMBOL_WARN} ", style="kite.pending")
        body.append("Could not open a browser — open this URL:\n", style="kite.pending")
    body.append(f"{GUTTER}┊ ", style="kite.muted")
    body.append(f"  {url}\n", style="cyan")
    if user_code:
        body.append(f"{GUTTER}┊\n", style="kite.muted")
        body.append(f"{GUTTER}┊ ", style="kite.pending")
        body.append("Enter this code if asked:\n", style="kite.pending")
        body.append(f"{GUTTER}┊ ", style="kite.muted")
        body.append(f"  {user_code}\n", style="bold cyan")
        body.append(f"{GUTTER}┊ ", style="kite.muted")
        body.append("Never share the code. Waiting until you finish (Ctrl+C to cancel).\n", style="kite.muted")
    elif extra:
        body.append(f"{GUTTER}┊ ", style="kite.muted")
        body.append(f"{extra}\n", style="kite.muted")
    else:
        body.append(f"{GUTTER}┊ ", style="kite.muted")
        body.append("Waiting until you finish in the browser (Ctrl+C to cancel).\n", style="kite.muted")
    return body


def render_credentials_table_rows(
    rows: list[tuple[str, bool, str]],
    *,
    default_provider: str = "",
    fingerprints: dict[str, str] | None = None,
) -> Text:
    """Plain-text credential rows for REPL /keys (no Rich Table)."""
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import credential_type_label, provider_credential_status
    from kite.providers.keys import api_key_env_names

    catalog = load_catalog()
    fingerprints = fingerprints or {}
    out = Text()
    out.append(f"{'provider':<14}{'type':<8}{'status':<16}{'detail'}\n", style="kite.muted bold")
    for name, ok, env in rows:
        try:
            spec = catalog.get(name)
            kind = credential_type_label(spec)
        except KeyError:
            kind = "—"
        status = provider_credential_status(ok=ok, env_col=env)
        if kind == "BYOK" and ok and env not in {"local", "oauth", "—"}:
            detail = fingerprints.get(name) or "••••"
        elif kind == "BYOS":
            detail = "oauth"
        elif env == "local":
            detail = "localhost"
        else:
            envs = []
            try:
                envs = api_key_env_names(catalog.get(name))
            except KeyError:
                pass
            detail = envs[0] if envs else env
        mark = " *" if name == default_provider else ""
        style = "kite.success" if ok else "kite.pending"
        if ok:
            status = f"{SYMBOL_OK} {status}"
        elif kind == "BYOS" and not ok:
            status = f"{SYMBOL_WARN} {status}"
        out.append(f"{name + mark:<14}", style=style)
        out.append(f"{kind:<8}", style="kite.muted")
        out.append(f"{status:<16}", style=style)
        out.append(f"{detail}\n", style="kite.muted")
    return out


def render_pick_list(
    items: list[tuple[str, str]],
    *,
    title: str,
    current: str | None = None,
    extra: int = 0,
    noun: str = "item",
    refreshable: bool = False,
) -> Text:
    """Left-bar numbered picker, same visual language as login panels."""
    body = Text()
    body.append(f"{GUTTER}┊ ", style="kite.pending")
    body.append(title, style="kite.pending bold")
    body.append("\n", style="kite.muted")
    for i, (item_id, label) in enumerate(items, start=1):
        is_current = bool(current and item_id == current)
        mark = " *" if is_current and "*" not in label else ""
        body.append(f"{GUTTER}┊ ", style="kite.muted")
        body.append(f"{i:>3}  ", style="kite.pick")
        body.append(f"{label}{mark}\n", style="kite.pick.current" if is_current else "")
    body.append(f"{GUTTER}┊\n", style="kite.muted")
    body.append(f"{GUTTER}┊ ", style="kite.muted")
    bits: list[str] = []
    if refreshable:
        bits.append("r = refresh from API")
    if extra > 0:
        bits.append(
            f"showing {len(items)} of {len(items) + extra} — type an id to pick any · empty/q = cancel"
        )
    else:
        bits.append(f"* = current · number or {noun} id · empty/q = cancel")
    body.append(" · ".join(bits) + "\n", style="kite.muted")
    return body
