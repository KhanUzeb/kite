"""Slash command routing fixes."""

from __future__ import annotations

from kite.ui.commands import LEGACY_ALIASES, parse_slash


def test_skill_not_legacy_alias() -> None:
    assert "skill" not in LEGACY_ALIASES
    assert "collapse" not in LEGACY_ALIASES


def test_parse_skill_routes_to_skill_not_skills() -> None:
    hit = parse_slash("/skill commit")
    assert hit.kind == "handled"
    assert hit.command == "skill"
    assert hit.arg == "commit"


def test_parse_collapse_stays_collapse() -> None:
    hit = parse_slash("/collapse")
    assert hit.command == "collapse"
