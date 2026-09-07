"""Terminal loader animations."""

from __future__ import annotations

from kite.ui.animations import default_loader_style, format_elapsed, loader_glyph


def test_loader_glyphs_cycle() -> None:
    a = loader_glyph("grid", 0)
    b = loader_glyph("grid", 1)
    assert a != b
    assert len(loader_glyph("dots", 0)) >= 1


def test_format_elapsed() -> None:
    assert format_elapsed(2.4) == "2.4s"
    assert format_elapsed(65) == "1m05s"


def test_default_loader_respects_env(monkeypatch) -> None:
    monkeypatch.setenv("KITE_LOADER", "dots")
    assert default_loader_style() == "dots"
    monkeypatch.delenv("KITE_LOADER", raising=False)
    assert default_loader_style() == "grid"
