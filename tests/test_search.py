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


def test_grep_files_only(tmp_path: Path) -> None:
    _tree(tmp_path)
    out = grep_search(pattern="def foo", root=tmp_path, cwd=str(tmp_path), files_only=True)
    assert out["ok"] is True
    assert "src/a.py" in out["output"]
    assert "return 1" not in out["output"]
    assert out.get("summary")


def test_grep_count_only(tmp_path: Path) -> None:
    _tree(tmp_path)
    out = grep_search(pattern="def ", root=tmp_path, cwd=str(tmp_path), count_only=True)
    assert out["ok"] is True
    assert ":" in out["output"]
    assert out["hits"] >= 2


def test_grep_grouped_output(tmp_path: Path) -> None:
    _tree(tmp_path)
    out = grep_search(pattern="def", root=tmp_path, cwd=str(tmp_path), max_hits=20)
    assert out["ok"] is True
    assert "hit" in out["output"]
    assert "summary" in out


def test_grep_glob_filter(tmp_path: Path) -> None:
    _tree(tmp_path)
    out = grep_search(
        pattern="def",
        root=tmp_path / "src",
        cwd=str(tmp_path),
        glob_pat="*.py",
        files_only=True,
    )
    assert out["ok"] is True
    assert "a.py" in out["output"]
    assert "tests" not in out["output"]


def test_grep_python_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kite.tools.search.shutil.which", lambda _name: None)
    _tree(tmp_path)
    out = grep_search(pattern="class Bar", root=tmp_path, cwd=str(tmp_path))
    assert out["ok"] is True
    assert out["engine"] == "python"
    assert "Bar" in out["output"]


def test_glob_recursive(tmp_path: Path) -> None:
    _tree(tmp_path)
    out = glob_search(pattern="**/*.py", root=tmp_path)
    assert out["ok"] is True
    assert out["count"] >= 3
    assert "src/a.py" in out["output"]


def test_glob_mtime_sort(tmp_path: Path) -> None:
    _tree(tmp_path)
    out = glob_search(pattern="**/*.py", root=tmp_path, sort="mtime")
    assert out["ok"] is True
    assert out["count"] >= 1


def test_ls_with_glob(tmp_path: Path) -> None:
    _tree(tmp_path)
    out = ls_search(path=tmp_path / "src", glob_pat="*.py")
    assert out["ok"] is True
    assert "a.py" in out["output"]
    assert "b.py" in out["output"]
    assert "subdir" not in out["output"]


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
