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
