"""Skills loader cache."""

from __future__ import annotations

import time

import kite.skills.loader as loader
from kite.skills.loader import load_skills
from kite.util.cache import TtlCache


def test_skills_cache_hit(workspace, monkeypatch) -> None:
    monkeypatch.setattr(loader, "_SKILLS_CACHE", TtlCache(60.0))

    first = load_skills(workspace)
    second = load_skills(workspace)
    assert first is second


def test_skills_cache_miss_after_ttl(workspace, monkeypatch) -> None:
    monkeypatch.setattr(loader, "_SKILLS_CACHE", TtlCache(0.01))

    first = load_skills(workspace)
    time.sleep(0.02)
    second = load_skills(workspace)
    assert first is not second
