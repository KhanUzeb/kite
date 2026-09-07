"""Project venv discovery and child env PATH."""

from __future__ import annotations

import sys

from kite.env.venv import apply_venv, discover_venv, prepare_child_env


def _path_value(env: dict[str, str]) -> str:
    if sys.platform == "win32":
        return env.get("Path", env.get("PATH", ""))
    return env.get("PATH", "")


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
    path_value = _path_value(env)
    assert str(bindir.resolve()) in path_value
    assert env["VIRTUAL_ENV"] == str(venv.resolve())


def test_prepare_child_env_respects_auto_venv_flag(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    venv = root / "venv"
    if sys.platform == "win32":
        bindir = venv / "Scripts"
        bindir.mkdir(parents=True)
        (bindir / "python.exe").write_text("", encoding="utf-8")
    else:
        bindir = venv / "bin"
        bindir.mkdir(parents=True)
        (bindir / "python").write_text("", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    bindir_resolved = str(bindir.resolve())

    off = prepare_child_env(cwd=root, auto_venv=False)
    on = prepare_child_env(cwd=root, auto_venv=True)

    assert bindir_resolved not in _path_value(off)
    assert off.get("VIRTUAL_ENV") != str(venv.resolve())
    assert on.get("VIRTUAL_ENV") == str(venv.resolve())
    assert bindir_resolved in _path_value(on)
