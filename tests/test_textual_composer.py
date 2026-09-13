"""Multi-line Textual composer behavior."""

from __future__ import annotations

from kite.ui.textual.composer import Composer


def test_composer_submit_message_has_control() -> None:
    composer = Composer()
    msg = Composer.Submitted(composer, "hi")
    assert msg.control is composer
    assert msg.text == "hi"
