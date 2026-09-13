"""Project trust store and approval skip helpers."""

from __future__ import annotations

from pathlib import Path

from kite.guardrails import project_trust as pt


def test_mark_and_check_trusted(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pt, "kite_home", lambda: home)
    monkeypatch.setattr(pt, "ensure_home", lambda: home)

    root = tmp_path / "repo"
    root.mkdir()
    assert pt.is_project_trusted(str(root)) is False
    pt.mark_project_trusted(str(root))
    assert pt.is_project_trusted(str(root)) is True
    assert pt.revoke_project_trust(str(root)) is True
    assert pt.is_project_trusted(str(root)) is False


def test_project_toml_trust(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pt, "kite_home", lambda: home)

    root = tmp_path / "repo"
    kite = root / ".kite"
    kite.mkdir(parents=True)
    (kite / "project.toml").write_text("[project]\ntrust = true\n", encoding="utf-8")
    assert pt.is_project_trusted(str(root)) is True
    assert pt.skips_nested_agent_approval(str(root)) is True


def test_skips_nested_when_not_trusted(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pt, "kite_home", lambda: home)
    root = tmp_path / "repo"
    root.mkdir()
    assert pt.skips_nested_agent_approval(str(root)) is False


def test_without_nested_agent_if_trusted(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pt, "kite_home", lambda: home)
    monkeypatch.setattr(pt, "ensure_home", lambda: home)
    root = tmp_path / "repo"
    root.mkdir()
    pt.mark_project_trusted(str(root))
    effects = {"nested_agent", "workspace_write"}
    trimmed = pt.without_nested_agent_if_trusted(effects, str(root))
    assert "nested_agent" not in trimmed
    assert "workspace_write" in trimmed
