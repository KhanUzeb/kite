"""Install skills from npm/npx/git specs; mark user skills in / menu."""

from __future__ import annotations

from pathlib import Path

from kite.cli.slash import CommandIndex, SlashSpec, resolve_slash
from kite.skills.install import _copy_skill_trees, parse_install_spec
from kite.skills.loader import Skill, classify_skill_dir, invalidate_skills, load_skills
from kite.ui.complete import _slash_display
from kite.ui.theme import glyph, reset_prefs


def test_parse_npx_npm_and_github() -> None:
    assert parse_install_spec("npx @scope/cool-skill") == ("npm", "@scope/cool-skill")
    assert parse_install_spec("npm i foo") == ("npm", "foo")
    assert parse_install_spec("npx skills add owner/repo") == (
        "git",
        "https://github.com/owner/repo.git",
    )
    assert parse_install_spec("https://github.com/a/b.git") == ("git", "https://github.com/a/b.git")
    assert parse_install_spec("foo") == ("npm", "foo")


def test_parse_install_spec_requires_a_ref() -> None:
    try:
        parse_install_spec("npx --yes")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_copy_skill_trees_uses_frontmatter_name(tmp_path: Path) -> None:
    packed = tmp_path / "package"
    packed.mkdir()
    (packed / "SKILL.md").write_text("---\nname: cool-skill\n---\n# hi\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    names = _copy_skill_trees(tmp_path, dest, fallback="pkg")
    assert names == ["cool-skill"]
    assert (dest / "cool-skill" / "SKILL.md").is_file()


def test_copy_package_folder_uses_npm_fallback(tmp_path: Path) -> None:
    packed = tmp_path / "package"
    packed.mkdir()
    (packed / "SKILL.md").write_text("# no frontmatter\nDo the thing.\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    names = _copy_skill_trees(tmp_path, dest, fallback="@scope/my-skill")
    assert names == ["my-skill"]


def test_classify_user_vs_project_skills(kite_home: Path, tmp_path: Path) -> None:
    user_dir = kite_home / "skills"
    user_dir.mkdir()
    assert classify_skill_dir(user_dir, tmp_path) == "user"
    proj = tmp_path / ".kite" / "skills"
    proj.mkdir(parents=True)
    assert classify_skill_dir(proj, tmp_path) == "project"


def test_user_skill_loads_with_user_source(kite_home: Path, workspace: Path) -> None:
    skill_dir = kite_home / "skills" / "mine"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: mine\ndescription: from home\n---\n# mine\n", encoding="utf-8")
    invalidate_skills()
    skills = load_skills(workspace)
    mine = next(s for s in skills if s.name == "mine")
    assert mine.source == "user"


def test_user_skill_slash_display_has_home_mark(tmp_path: Path) -> None:
    reset_prefs(theme="auto", font="unicode")
    user = Skill(name="mine", path=tmp_path / "SKILL.md", content="x", description="hi", source="user")
    spec = SlashSpec(name="mine", kind="prompt", source="skill", description="hi")
    index = CommandIndex(specs={"mine": spec}, skills=[user])
    assert _slash_display(spec, index) == f"/mine {glyph('home')}"

    bundled = Skill(name="commit", path=tmp_path / "c", content="x", source="bundled")
    spec2 = SlashSpec(name="commit", kind="prompt", source="skill", description="")
    assert _slash_display(spec2, CommandIndex(specs={"commit": spec2}, skills=[bundled])) == "/commit"

    cmd = SlashSpec(name="mycmd", kind="prompt", source="user", description="")
    assert _slash_display(cmd, CommandIndex()) == "/mycmd"


def test_skill_add_routes_to_skills_install() -> None:
    result = resolve_slash("/skill add @foo/bar", CommandIndex())
    assert result.kind == "handled"
    assert result.command == "skills"
    assert result.arg == "add @foo/bar"
