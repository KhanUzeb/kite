"""Instruction file dedupe and per-file caps."""

from __future__ import annotations

from kite.context.discovery import MAX_INSTRUCTION_FILE_CHARS, discover_agents_files


def test_discover_agents_dedupes_instruction_basenames(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("root agents", encoding="utf-8")
    sub = root / "pkg"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("nested agents", encoding="utf-8")
    files = discover_agents_files(sub)
    basenames = [__import__("pathlib").Path(f.path).name for f in files]
    assert basenames.count("AGENTS.md") == 1
    assert "root agents" in files[0].content


def test_discover_agents_truncates_large_files(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    huge = "x" * (MAX_INSTRUCTION_FILE_CHARS + 500)
    (root / "KITE.md").write_text(huge, encoding="utf-8")
    files = discover_agents_files(root)
    assert len(files) == 1
    assert len(files[0].content) <= MAX_INSTRUCTION_FILE_CHARS
    assert files[0].content.endswith("...[truncated]...")
