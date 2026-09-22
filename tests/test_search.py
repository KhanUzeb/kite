"""grep / glob / ls search tools."""

from __future__ import annotations

from pathlib import Path

from kite.tools.search import glob_search, grep_search, ls_search


def _tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("class Bar:\n    pass\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_foo():\n    assert foo()\n", encoding="utf-8")


def test_grep_output_modes(tmp_path: Path) -> None:
    _tree(tmp_path)
    files_only = grep_search(pattern="def foo", root=tmp_path, cwd=str(tmp_path), files_only=True)
    assert files_only["ok"] is True
    assert "src/a.py" in files_only["output"]
    assert "return 1" not in files_only["output"]
    assert files_only.get("summary")

    count_only = grep_search(pattern="def ", root=tmp_path, cwd=str(tmp_path), count_only=True)
    assert count_only["ok"] is True
    assert ":" in count_only["output"]
    assert count_only["hits"] >= 2

    grouped = grep_search(pattern="def", root=tmp_path, cwd=str(tmp_path), max_hits=20)
    assert grouped["ok"] is True
    assert "hit" in grouped["output"]
    assert "summary" in grouped


def test_grep_filter_and_python_fallback(monkeypatch, tmp_path: Path) -> None:
    _tree(tmp_path)
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

    monkeypatch.setattr("kite.tools.search.shutil.which", lambda _name: None)
    fallback = grep_search(pattern="class Bar", root=tmp_path, cwd=str(tmp_path))
    assert fallback["ok"] is True
    assert fallback["engine"] == "python"
    assert "Bar" in fallback["output"]


def test_glob_and_ls(tmp_path: Path) -> None:
    _tree(tmp_path)
    recursive = glob_search(pattern="**/*.py", root=tmp_path)
    assert recursive["ok"] is True
    assert recursive["count"] >= 3
    assert "src/a.py" in recursive["output"]

    by_mtime = glob_search(pattern="**/*.py", root=tmp_path, sort="mtime")
    assert by_mtime["ok"] is True
    assert by_mtime["count"] >= 1

    listed = ls_search(path=tmp_path / "src", glob_pat="*.py")
    assert listed["ok"] is True
    assert "a.py" in listed["output"]
    assert "b.py" in listed["output"]
    assert "subdir" not in listed["output"]


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
