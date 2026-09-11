"""Skill install specs, classification, and home/project loading."""

from __future__ import annotations

from pathlib import Path

from kite.skills.install import _copy_skill_trees, parse_install_spec
from kite.skills.loader import classify_skill_dir, invalidate_skills, load_skills


def test_parse_install_specs_and_copy(tmp_path: Path) -> None:
    assert parse_install_spec("npx @scope/cool-skill") == ("npm", "@scope/cool-skill")
    assert parse_install_spec("npx skills add owner/repo") == ("git", "https://github.com/owner/repo.git")
    assert parse_install_spec("foo") == ("npm", "foo")
    skill = tmp_path / "mine"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# mine\n", encoding="utf-8")
    kind, ref = parse_install_spec(str(skill))
    assert kind == "link" and Path(ref) == skill
    packed = tmp_path / "package"
    packed.mkdir()
    (packed / "SKILL.md").write_text("---\nname: cool-skill\n---\n# hi\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    assert _copy_skill_trees(packed, dest, fallback="pkg") == ["cool-skill"]


def test_classify_and_load_user_skills(kite_home: Path, workspace: Path, tmp_path: Path, monkeypatch) -> None:
    user_dir = kite_home / "skills"
    user_dir.mkdir()
    assert classify_skill_dir(user_dir, tmp_path) == "user"
    proj = tmp_path / ".kite" / "skills"
    proj.mkdir(parents=True)
    assert classify_skill_dir(proj, tmp_path) == "project"
    skill_dir = kite_home / "skills" / "mine"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: mine\ndescription: from home\n---\n# mine\n", encoding="utf-8")
    invalidate_skills()
    mine = next(s for s in load_skills(workspace) if s.name == "mine")
    assert mine.source == "user"
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    agents = tmp_path / ".agents" / "skills" / "orca-cli"
    agents.mkdir(parents=True)
    (agents / "SKILL.md").write_text("---\nname: orca-cli\ndescription: orca helper\n---\n# orca\n", encoding="utf-8")
    invalidate_skills()
    skill = next(s for s in load_skills(workspace) if s.name == "orca-cli")
    assert skill.source == "user"
    assert classify_skill_dir(tmp_path / ".agents" / "skills", workspace) == "user"
