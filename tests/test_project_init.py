"""Project bootstrap — AGENTS.md scaffolding and bootstrap nudge."""

from __future__ import annotations

import subprocess
from pathlib import Path

from kite.context.discovery import gather_project_context
from kite.context.project_init import (
    detect_ecosystem,
    needs_agents_bootstrap,
    render_agents_md,
    scaffold_project_docs,
)


def test_scaffold_agents_and_kite(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname="demo"\ndescription="Demo project"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    result = scaffold_project_docs(root)
    assert result.agents is not None and result.agents.action == "created"
    assert result.kite is not None and result.kite.action == "created"
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Demo project" in agents
    assert "pytest" in agents
    again = scaffold_project_docs(root)
    assert again.agents is not None and again.agents.action == "skipped"


def test_force_overwrite_creates_backup(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text('{"name":"x","scripts":{"test":"npm test"}}', encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    scaffold_project_docs(root)
    (root / "AGENTS.md").write_text("# old\n", encoding="utf-8")
    forced = scaffold_project_docs(root, force=True)
    assert forced.agents is not None and forced.agents.action == "overwritten"
    assert forced.agents.backup is not None and forced.agents.backup.is_file()
    assert "Setup commands" in (root / "AGENTS.md").read_text(encoding="utf-8")


def test_bootstrap_nudge_when_missing_agents(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    assert needs_agents_bootstrap(root)
    rendered = gather_project_context(root).render_for_prompt()
    assert "<bootstrap_check>" in rendered


def test_bootstrap_nudge_absent_when_agents_present(tmp_path: Path) -> None:
    root = tmp_path / "proj2"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# ok\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    assert not needs_agents_bootstrap(root)
    rendered = gather_project_context(root).render_for_prompt()
    assert "<bootstrap_check>" not in rendered


def test_detect_ecosystem_node_scripts(tmp_path: Path) -> None:
    root = tmp_path / "node"
    root.mkdir()
    (root / "package.json").write_text(
        '{"scripts":{"test":"vitest run","lint":"eslint .","typecheck":"tsc -p ."}}',
        encoding="utf-8",
    )
    eco = detect_ecosystem(root)
    assert eco.test == "vitest run"
    assert eco.lint == "eslint ."
    assert eco.typecheck == "tsc -p ."
    md = render_agents_md(root)
    assert "vitest run" in md
