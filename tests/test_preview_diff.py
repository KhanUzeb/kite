"""Approval diff previews without reading whole files."""

from __future__ import annotations

from pathlib import Path

from kite.ui.diff import (
    count_diff_lines,
    make_unified_diff,
    preview_mutating_diff,
    preview_patch_diff,
    render_diff,
    render_diff_stat,
)


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


def test_count_diff_lines_skips_headers() -> None:
    diff = make_unified_diff("src/foo.py", "a\nb\nc\n", "a\nB\nc\nD\n")
    added, deleted = count_diff_lines(diff)
    assert added == 2
    assert deleted == 1


def test_render_diff_stat_is_color_coded() -> None:
    text = render_diff_stat(125, 21, bar=False)
    assert text.plain == "+125,-21"
    styles = [span.style for span in text.spans]
    assert "kite.diff.add" in styles
    assert "kite.diff.del" in styles


def test_render_diff_leads_with_stat() -> None:
    diff = (
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " keep\n"
        "-old\n"
        "+new\n"
        "+extra\n"
    )
    plain = render_diff(diff).plain
    assert "+2,-1" in plain
    assert "src/foo.py" in plain
    assert "+new" in plain


def test_render_diff_color_codes_hunk_lines() -> None:
    diff = (
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " keep\n"
        "-old\n"
        "+new\n"
    )
    text = render_diff(diff)
    styles = {span.style for span in text.spans}
    assert "kite.diff.add" in styles
    assert "kite.diff.del" in styles
    assert "kite.diff.hunk" in styles
    assert "kite.diff.ctx" in styles
    assert "kite.diff.meta" in styles


def test_dark_palette_is_near_black_ready() -> None:
    from kite.ui.theme import palette, reset_prefs, set_theme

    reset_prefs(theme="auto", font="unicode")
    try:
        set_theme("dark")
        styles = palette()["styles"]
        assert "bright_cyan" in styles["kite.brand"] or "cyan" in styles["kite.brand"]
        assert "bright_green" in styles["kite.diff.add"] or "green" in styles["kite.diff.add"]
        assert "kite.diff.ctx" in styles
    finally:
        reset_prefs(theme="auto", font="unicode")


def test_pt_style_dark_menu_is_near_black() -> None:
    from kite.ui.complete import _PT, _pt_style

    if not _PT:
        return
    style = _pt_style(dark=True)
    assert style is not None
    rules = dict(style.style_rules)
    assert "bg:#050505" in rules["completion-menu"]
    assert "ansibrightcyan" in rules["prompt"]

