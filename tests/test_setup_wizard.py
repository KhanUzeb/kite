"""Setup wizard helpers (non-interactive)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from kite.cli.setup import run_setup_wizard
from kite.config import UserConfig
from kite.ui.style import KITE_THEME


def test_run_setup_wizard_reports_already_configured(kite_home) -> None:
    cfg = UserConfig.load()
    cfg.default_provider = "ollama"
    cfg.default_model = "llama3.2"
    cfg.save()

    buf = StringIO()
    console = Console(file=buf, width=100, force_terminal=True, theme=KITE_THEME)
    code = run_setup_wizard(console)
    out = buf.getvalue()
    assert code == 0
    assert "Already configured" in out or "ollama" in out
