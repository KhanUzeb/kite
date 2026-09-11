"""RunDisplay sink that posts renderables to a Textual app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kite.ui.render import RunDisplay

if TYPE_CHECKING:
    from kite.ui.textual.app import KiteApp


class TextualRunDisplay(RunDisplay):
    """Event renderer that writes into the Textual transcript instead of stdout."""

    def __init__(self, app: KiteApp, **kwargs: Any) -> None:
        self._textual_app = app
        super().__init__(console=app.rich_console, **kwargs)

    def _print(self, *args: Any, **kwargs: Any) -> None:
        renderable = args[0] if len(args) == 1 else args
        markup = kwargs.get("markup", True)
        highlight = kwargs.get("highlight", True)
        self._textual_app.write_transcript(renderable, markup=markup, highlight=highlight)
