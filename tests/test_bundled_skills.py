"""Bundled skills are discoverable by the loader."""

from __future__ import annotations

from pathlib import Path

from kite.skills.loader import invalidate_skills, load_skills


def test_bundled_skills_include_core_playbooks(kite_home: Path, workspace: Path) -> None:
    del kite_home  # isolate ~/.kite so user skills cannot shadow bundled names
    invalidate_skills()
    names = {s.name for s in load_skills(workspace) if s.source == "bundled"}
    assert {"commit", "debug", "review", "orchestrate", "research", "pr"} <= names
