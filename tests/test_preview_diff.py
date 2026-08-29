"""Approval diff previews without reading whole files."""

from __future__ import annotations

from pathlib import Path

from kite.ui.diff import preview_mutating_diff, preview_patch_diff


def test_preview_patch_diff_from_args_only() -> None:
    diff = preview_patch_diff("src/foo.py", "old line\n", "new line\n")
    assert "-old line" in diff
    assert "+new line" in diff
    assert "patch preview" in diff


def test_preview_edit_large_file_avoids_read_text(tmp_path, monkeypatch) -> None:
    path = tmp_path / "big.py"
    path.write_text("prefix\nneedle\nsuffix\n" + ("x" * 100_000))
    original = Path.read_text

    def spy_read_text(self: Path, *args, **kwargs) -> str:
        if self == path:
            raise AssertionError("preview should not read the entire large file")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    diff = preview_mutating_diff(
        "edit",
        path,
        {"path": str(path), "old": "needle", "new": "found"},
        cwd=tmp_path,
    )
    assert "-needle" in diff
    assert "+found" in diff


def test_preview_write_large_file_uses_size_hint(tmp_path, monkeypatch) -> None:
    path = tmp_path / "big.txt"
    path.write_text("z" * 80_000)
    original = Path.read_text

    def spy_read_text(self: Path, *args, **kwargs) -> str:
        if self == path:
            raise AssertionError("preview should not read the entire large file")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    diff = preview_mutating_diff(
        "write",
        path,
        {"path": str(path), "content": "hello\nworld\n"},
        cwd=tmp_path,
    )
    assert "replaces entire file" in diff
    assert "+hello" in diff
