"""Line-ending preservation: edits keep on-disk endings, new files use OS default."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from kite.tools.line_endings import (
    CRLF,
    LF,
    detect_line_ending,
    encode_with_ending,
    new_file_ending,
    normalize_newlines,
    os_default_ending,
    verify_line_endings,
    write_text_preserving,
)


def _needs_git() -> None:
    import pytest

    if shutil.which("git") is None:
        pytest.skip("git not on PATH")


def test_detect_normalize_encode_and_os_default(tmp_path: Path) -> None:
    crlf = tmp_path / "a.txt"
    crlf.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    assert detect_line_ending(crlf) == CRLF
    lf = tmp_path / "b.txt"
    lf.write_bytes(b"one\ntwo\nthree\n")
    assert detect_line_ending(lf) == LF
    mixed = tmp_path / "c.txt"
    mixed.write_bytes(b"one\r\ntwo\r\nthree\n")
    assert detect_line_ending(mixed) == CRLF
    assert detect_line_ending(tmp_path / "missing.txt") is None
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert detect_line_ending(empty) is None
    assert normalize_newlines("a\r\nb\rc\n") == "a\nb\nc\n"
    assert encode_with_ending("a\nb\n", CRLF) == b"a\r\nb\r\n"
    assert encode_with_ending("a\r\nb\n", LF) == b"a\nb\n"
    assert os_default_ending() == (CRLF if sys.platform == "win32" else LF)


def test_new_and_existing_file_endings(tmp_path: Path) -> None:
    target = tmp_path / "fresh.txt"
    assert new_file_ending(target) == os_default_ending()
    ending = write_text_preserving(target, "x\ny\n")
    assert ending == os_default_ending()
    raw = target.read_bytes()
    assert (b"\r\n" in raw) == (os_default_ending() == CRLF)
    # The reported bug: LF file rewritten on Windows must stay LF.
    keep = tmp_path / "keep.txt"
    keep.write_bytes(b"alpha\nbeta\ngamma\n")
    lf_ending = write_text_preserving(keep, "alpha\nBETA\ngamma\n")
    assert lf_ending == LF
    assert keep.read_bytes() == b"alpha\nBETA\ngamma\n"
    assert verify_line_endings(keep, LF)
    crlf_keep = tmp_path / "keep-crlf.txt"
    crlf_keep.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
    crlf_ending = write_text_preserving(crlf_keep, "alpha\r\nBETA\r\ngamma\r\n")
    assert crlf_ending == CRLF
    assert crlf_keep.read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"
    _needs_git()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    (tmp_path / ".gitattributes").write_text("*.txt eol=crlf\n", encoding="utf-8")
    note = tmp_path / "note.txt"
    assert new_file_ending(note) == CRLF
    lf_attr = tmp_path / ".gitattributes"
    lf_attr.write_text("*.txt eol=lf\n", encoding="utf-8")
    assert new_file_ending(note) == LF
    (tmp_path / ".editorconfig").write_text(
        "root = true\n\n[*.md]\nend_of_line = crlf\n", encoding="utf-8"
    )
    assert new_file_ending(tmp_path / "doc.md") == CRLF
    assert new_file_ending(tmp_path / "code.py") == os_default_ending()


def _coding_tools(cwd: Path) -> dict:
    from kite.config import GuardrailConfig
    from kite.guardrails import GuardrailPolicy
    from kite.tools.coding import make_coding_tools

    tools = make_coding_tools(
        cwd=str(cwd),
        guardrails=GuardrailPolicy(GuardrailConfig(), cwd),
        enabled=["write", "edit"],
    )
    return {t.name: t for t in tools}


def test_write_and_edit_tools_preserve_endings(tmp_path: Path) -> None:
    tools = _coding_tools(tmp_path)
    target = tmp_path / "app.py"
    target.write_bytes(b"line1\nline2\nline3\n")
    result = tools["write"].run({"path": str(target), "content": "line1\nLINE2\nline3\n"})
    assert result["ok"] is True
    assert target.read_bytes() == b"line1\nLINE2\nline3\n"
    assert result["line_ending"] == "lf"
    srv = tmp_path / "srv.txt"
    before = b"a\r\nb\r\nc\r\nd\r\n"
    srv.write_bytes(before)
    edit_result = tools["edit"].run({"path": str(srv), "old": "b", "new": "B"})
    assert edit_result["ok"] is True
    after = srv.read_bytes()
    assert after == b"a\r\nB\r\nc\r\nd\r\n"
    assert edit_result["line_ending"] == "crlf"
    # Only one line differs — no whole-file churn.
    before_lines = before.split(b"\r\n")
    after_lines = after.split(b"\r\n")
    assert len(before_lines) == len(after_lines)
    assert sum(1 for i in range(len(before_lines)) if before_lines[i] != after_lines[i]) == 1
    brand_new = tmp_path / "brand-new.txt"
    new_result = tools["write"].run({"path": str(brand_new), "content": "hello\nworld\n"})
    assert new_result["ok"] is True
    new_raw = brand_new.read_bytes()
    if os_default_ending() == CRLF:
        assert new_raw == b"hello\r\nworld\r\n"
    else:
        assert new_raw == b"hello\nworld\n"


def test_apply_diff_preserves_endings(tmp_path: Path) -> None:
    from kite.cli.apply_cmd import apply_unified_diff

    target = tmp_path / "f.py"
    target.write_bytes(b"x = 1\r\ny = 2\r\n")
    diff = "--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,2 @@\n-x = 1\n+x = 10\n y = 2\n"
    result = apply_unified_diff(diff, cwd=str(tmp_path))
    assert result["count"] == 1
    assert target.read_bytes() == b"x = 10\r\ny = 2\r\n"
