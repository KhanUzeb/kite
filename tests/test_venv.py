"""Project venv discovery and child env PATH."""

from __future__ import annotations

import sys

from kite.env.venv import apply_venv, discover_venv, prepare_child_env


def test_discover_venv_finds_dot_venv(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    venv = root / ".venv"
    if sys.platform == "win32":
        scripts = venv / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "python.exe").write_text("", encoding="utf-8")
    else:
        bindir = venv / "bin"
        bindir.mkdir(parents=True)
        (bindir / "python").write_text("", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    found = discover_venv(root)
    assert found == venv.resolve()


def test_apply_venv_prepends_path(tmp_path) -> None:
    venv = tmp_path / ".venv"
    if sys.platform == "win32":
        bindir = venv / "Scripts"
    else:
        bindir = venv / "bin"
    bindir.mkdir(parents=True)
    env = apply_venv({"PATH": "/usr/bin"}, venv)
    path_key = "Path" if sys.platform == "win32" and "Path" in env else "PATH"
    assert str(bindir.resolve()) in env[path_key]
    assert env["VIRTUAL_ENV"] == str(venv.resolve())


def test_prepare_child_env_respects_auto_venv_flag(tmp_path, monkeypatch) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    venv = root / "venv"
    if sys.platform == "win32":
        (venv / "Scripts").mkdir(parents=True)
        (venv / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    else:
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").write_text("", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    off = prepare_child_env(cwd=root, auto_venv=False)
    on = prepare_child_env(cwd=root, auto_venv=True)
    assert "VIRTUAL_ENV" not in off
    assert on.get("VIRTUAL_ENV") == str(venv.resolve())
