"""apply_cmd workspace checks."""

from __future__ import annotations

from pathlib import Path

from kite.cli.apply_cmd import _path_inside_workspace, apply_unified_diff


def test_sibling_prefix_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "root2"
    sibling.mkdir()
    assert not _path_inside_workspace(sibling, root)


def test_apply_unified_diff_flushes_last_file(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("hello\n", encoding="utf-8")
    diff = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-hello
+world
"""
    result = apply_unified_diff(diff, cwd=str(tmp_path))
    assert result["count"] == 1
    assert target.read_text(encoding="utf-8") == "world\n"
