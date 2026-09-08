"""Skill trust and provenance."""

from __future__ import annotations

import json
from pathlib import Path

from kite.skills.loader import Skill, build_skill_index, load_skills, skill_trust
from kite.skills.install import _write_provenance


def test_skill_trust_levels() -> None:
    assert skill_trust("bundled", "bundled") == "trusted"
    assert skill_trust("user", "user-local") == "untrusted"
    assert skill_trust("user", "npm") == "untrusted"
    assert skill_trust("project", "project") == "untrusted"


def test_skill_index_includes_trust_metadata() -> None:
    skills = [
        Skill(
            name="demo",
            path=Path("/tmp/demo/SKILL.md"),
            content="do thing",
            description="demo",
            source="user",
            trust="untrusted",
            origin="npm",
        )
    ]
    index = build_skill_index(skills)
    assert "<trust>untrusted</trust>" in index
    assert "<origin>npm</origin>" in index
    assert "<source>user</source>" in index


def test_provenance_file_sets_origin(tmp_path, kite_home) -> None:
    skill_dir = kite_home / "skills" / "remote-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: remote-skill\n---\nbody\n", encoding="utf-8")
    _write_provenance(skill_dir, "npm", "@acme/skill-pack")
    prov = json.loads((skill_dir / ".kite-provenance.json").read_text(encoding="utf-8"))
    assert prov["origin"] == "npm"
    skills = load_skills(tmp_path)
    match = next((s for s in skills if s.name == "remote-skill"), None)
    assert match is not None
    assert match.origin == "npm"
    assert match.trust == "untrusted"
