"""CI hints, verification in project context, memory layers prompt."""

from __future__ import annotations

import subprocess
from pathlib import Path

from kite.context.ci_hints import canonical_test_command
from kite.context.discovery import gather_project_context, invalidate_project_context_cache
from kite.prompts import assemble_system_prompt, load_prompt_template
from kite.config.runtime import load_runtime_config


def test_canonical_test_from_github_workflow(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows" / "test.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text(
        "jobs:\n  ci:\n    steps:\n      - run: pytest -q tests/\n",
        encoding="utf-8",
    )
    assert canonical_test_command(tmp_path) == "pytest"


def test_project_context_includes_ci_verification(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    wf = root / ".github" / "workflows" / "ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("steps:\n  - run: ./scripts/ci_check.sh\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    invalidate_project_context_cache()
    ctx = gather_project_context(root)
    assert ctx.verification_source == "ci"
    assert ctx.verification_command == "./scripts/ci_check.sh"
    rendered = ctx.render_for_prompt()
    assert "Canonical verification" in rendered
    assert "./scripts/ci_check.sh" in rendered


def test_worktree_reminder_in_git_project(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    invalidate_project_context_cache()
    rendered = gather_project_context(root).render_for_prompt()
    assert "<worktree-reminder>" in rendered


def test_workspace_profile_uses_ci_command(tmp_path: Path) -> None:
    from kite.application.verification import discover_workspace_profile

    root = tmp_path / "proj"
    root.mkdir()
    wf = root / ".github" / "workflows" / "t.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("run: pytest -q\n", encoding="utf-8")
    profile = discover_workspace_profile(root)
    assert profile.workspace_commands == ("pytest",)


def test_memory_layers_in_system_prompt() -> None:
    body = load_prompt_template("memory_layers")
    assert "AGENTS.md" in body and "USER.md" in body
    system = assemble_system_prompt(config=load_runtime_config(), project_context=None, skills=[])
    assert "Memory layers" in system
