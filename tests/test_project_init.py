"""Project bootstrap — AGENTS.md scaffolding and bootstrap nudge."""

from __future__ import annotations

import subprocess
from pathlib import Path

from kite.application.verification import discover_workspace_profile
from kite.config.runtime import load_runtime_config
from kite.context.ci_hints import canonical_test_command
from kite.context.discovery import gather_project_context, invalidate_project_context_cache
from kite.context.project_init import (
    detect_ecosystem,
    needs_agents_bootstrap,
    render_agents_md,
    scaffold_project_docs,
)
from kite.context.verify_hint import resolve_verification_command
from kite.prompts import assemble_system_prompt, load_prompt_template


def test_scaffold_and_force_overwrite(tmp_path: Path) -> None:
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

    node = tmp_path / "node-proj"
    node.mkdir()
    (node / "package.json").write_text('{"name":"x","scripts":{"test":"npm test"}}', encoding="utf-8")
    subprocess.run(["git", "init"], cwd=node, check=True, capture_output=True)
    scaffold_project_docs(node)
    (node / "AGENTS.md").write_text("# old\n", encoding="utf-8")
    forced = scaffold_project_docs(node, force=True)
    assert forced.agents is not None and forced.agents.action == "overwritten"
    assert forced.agents.backup is not None and forced.agents.backup.is_file()
    assert "## Setup" in (node / "AGENTS.md").read_text(encoding="utf-8")


def test_bootstrap_nudge_present_and_absent(tmp_path: Path) -> None:
    missing = tmp_path / "proj"
    missing.mkdir()
    (missing / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=missing, check=True, capture_output=True)
    assert needs_agents_bootstrap(missing)
    rendered = gather_project_context(missing).render_for_prompt()
    assert "<bootstrap_check>" in rendered
    assert "`init` skill" in rendered

    present = tmp_path / "proj2"
    present.mkdir()
    (present / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (present / "AGENTS.md").write_text("# ok\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=present, check=True, capture_output=True)
    assert not needs_agents_bootstrap(present)
    rendered_present = gather_project_context(present).render_for_prompt()
    assert "<bootstrap_check>" not in rendered_present


def test_ecosystem_ci_verify_and_context_block(tmp_path: Path) -> None:
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

    wf = tmp_path / ".github" / "workflows" / "test.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("run: pytest -q\n", encoding="utf-8")
    assert canonical_test_command(tmp_path) == "pytest"
    assert resolve_verification_command(tmp_path) == ("pytest", "ci")
    assert discover_workspace_profile(tmp_path).workspace_commands == ("pytest",)

    ci_root = tmp_path / "proj"
    ci_root.mkdir()
    (ci_root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (ci_root / ".github" / "workflows" / "ci.yml").parent.mkdir(parents=True)
    (ci_root / ".github" / "workflows" / "ci.yml").write_text(
        "run: ./scripts/ci_check.sh\n", encoding="utf-8"
    )
    subprocess.run(["git", "init"], cwd=ci_root, check=True, capture_output=True)
    invalidate_project_context_cache()
    rendered = gather_project_context(ci_root).render_for_prompt()
    assert "Canonical verification" in rendered and "<worktree-reminder>" in rendered


def test_memory_layers_prompt() -> None:
    assert "AGENTS.md" in load_prompt_template("memory_layers")
    assert "Memory layers" in assemble_system_prompt(config=load_runtime_config(), skills=[])


def test_stable_setup_split_keeps_prefix_cacheable(tmp_path) -> None:
    from kite.prompts import split_system_and_setup

    config = load_runtime_config()
    stable, setup = split_system_and_setup(config=config, skills=[])
    assert "UTC:" not in stable and "UTC:" in setup
    assert "Kite" in stable and len(stable) > 500
