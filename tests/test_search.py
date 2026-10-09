"""grep / glob / ls search tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.tools.search import glob_search, grep_search, ls_search


def _tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("class Bar:\n    pass\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_foo():\n    assert foo()\n", encoding="utf-8")


def test_grep_filter_and_python_fallback(monkeypatch, tmp_path: Path) -> None:
    _tree(tmp_path)
    (tmp_path / "src" / "notes.txt").write_text("def not_python(): pass\n", encoding="utf-8")
    filtered = grep_search(
        pattern="def",
        root=tmp_path / "src",
        cwd=str(tmp_path),
        glob_pat="*.py",
        files_only=True,
    )
    assert filtered["ok"] is True
    assert "a.py" in filtered["output"]
    assert "tests" not in filtered["output"]
    assert "notes.txt" not in filtered["output"]

    monkeypatch.setattr("kite.tools.search.shutil.which", lambda _name: None)
    fallback = grep_search(pattern="class Bar", root=tmp_path, cwd=str(tmp_path))
    assert fallback["ok"] is True
    assert fallback["engine"] == "python"
    assert "Bar" in fallback["output"]


def test_glob_and_ls(tmp_path: Path) -> None:
    _tree(tmp_path)
    recursive = glob_search(pattern="**/*.py", root=tmp_path)
    assert recursive["ok"] is True
    assert recursive["count"] == 3
    assert "src/a.py" in recursive["output"]

    listed = ls_search(path=tmp_path / "src", glob_pat="*.py")
    assert listed["ok"] is True
    assert "a.py" in listed["output"]
    assert "b.py" in listed["output"]


def test_glob_mtime_sort_skips_unreadable_files(tmp_path: Path, monkeypatch) -> None:
    """Permission-denied entries must not crash glob (is_file re-raises EACCES)."""
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y\n", encoding="utf-8")
    real_stat = Path.stat

    def flaky_stat(self, *args, **kwargs):
        if self.name == "b.py":
            raise OSError("permission denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    out = glob_search(pattern="*.py", root=tmp_path, sort="mtime")
    assert out["ok"] is True
    assert "a.py" in out["output"]
    assert "b.py" not in out["output"]


def test_grep_skips_credential_files_and_literal_patterns(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("token = visible\n", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=supersecret\n", encoding="utf-8")
    (tmp_path / "config.env").write_text("API_KEY=alsosecret\n", encoding="utf-8")
    monkeypatch.setattr("kite.tools.search.shutil.which", lambda _name: None)
    hidden = grep_search(pattern="API_KEY", root=tmp_path, cwd=str(tmp_path))
    assert hidden["ok"] is True
    assert "supersecret" not in hidden["output"] and "alsosecret" not in hidden["output"]
    visible = grep_search(pattern="visible", root=tmp_path, cwd=str(tmp_path))
    assert "src/a.py" in visible["output"]
    literal = grep_search(pattern="token =", root=tmp_path, cwd=str(tmp_path), fixed=True)
    assert literal["ok"] is True and "src/a.py" in literal["output"]
    special = grep_search(pattern="[error]", root=tmp_path, cwd=str(tmp_path), fixed=True)
    assert special["ok"] is True and "invalid regex" not in special.get("error", "")
    bad = grep_search(pattern="[", root=tmp_path, cwd=str(tmp_path))
    assert bad["ok"] is False and "invalid regex" in bad["output"]


@pytest.mark.parametrize("fallback", [False, True])
def test_grep_limits_context_and_colons(tmp_path, monkeypatch, fallback):
    import shutil

    if fallback:
        monkeypatch.setattr("kite.tools.search.shutil.which", lambda _name: None)
    elif not shutil.which("rg"):
        pytest.skip("ripgrep not installed")
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("before\nneedle: detail: value\nafter\n", encoding="utf-8")
    (tmp_path / "credentials.json").write_text("needle: do-not-show\n", encoding="utf-8")
    (tmp_path / "config.env").write_text("needle: do-not-show\n", encoding="utf-8")
    args = {"pattern": "needle", "root": tmp_path, "cwd": str(tmp_path), "glob_pat": "*"}
    grouped = grep_search(**args, max_hits=2)
    assert grouped["hits"] == 2 and "2: needle: detail: value" in grouped["output"]
    assert "do-not-show" not in grouped["output"]
    surrounding = grep_search(**args, max_hits=1, context=1)
    assert surrounding["hits"] == 1
    assert "-1-before" in surrounding["output"] and "-3-after" in surrounding["output"]
    assert "do-not-show" not in surrounding["output"]
    counted = grep_search(**args, count_only=True, max_files=1)
    assert counted["hits"] == 3 and counted["files"] == 3
    assert len(counted["output"].splitlines()) == 1
    files = grep_search(**args, files_only=True, max_files=1)
    assert files["files"] == 3 and "+2 more files" in files["output"]
    single = grep_search(pattern="needle", root=tmp_path / "a.py", cwd=str(tmp_path))
    assert "a.py (1 hit)" in single["output"]
    boundary = tmp_path / "boundary.py"
    boundary.write_text("needle" + " " * 222 + "api_key=sensitivedataabcdefghijklmnop\n", encoding="utf-8")
    redacted = grep_search(pattern="needle", root=boundary, cwd=str(tmp_path))
    assert "sens" not in redacted["output"]
