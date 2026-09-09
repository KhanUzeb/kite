"""Shared BYOS login UI helpers."""

from __future__ import annotations

import os
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from kite.providers.catalog import ProviderSpec
from kite.ui.credentials import render_byos_login_panel

if TYPE_CHECKING:
    from rich.console import Console

T = TypeVar("T")


def open_browser(url: str) -> bool:
    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError:
            return False
    return False


def show_byos_panel(
    spec: ProviderSpec,
    *,
    url: str,
    console: Console | None,
    user_code: str = "",
    browser_opened: bool | None = False,
    extra: str = "",
) -> None:
    panel = render_byos_login_panel(
        spec,
        url=url,
        user_code=user_code,
        browser_opened=browser_opened,
        extra=extra,
    )
    if console is not None:
        console.print(panel)
        return
    print(str(panel), flush=True)


def wait_with_status(console: Console | None, message: str, work: Callable[[], T]) -> T:
    if console is not None:
        with console.status(message):
            return work()
    return work()
