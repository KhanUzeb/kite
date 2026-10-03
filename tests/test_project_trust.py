"""Project trust store and approval skip helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from kite.guardrails import project_trust as pt


def _c_test_trust_store_mark_toml_and_revoke(tmp_path: Path, monkeypatch) -> None:
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

    kite = root / ".kite"
    kite.mkdir(parents=True, exist_ok=True)
    (kite / "project.toml").write_text("[project]\ntrust = true\n", encoding="utf-8")
    assert pt.is_project_trusted(str(root)) is True
    assert pt.skips_nested_agent_approval(str(root)) is True


def _c_test_nested_agent_approval_gating(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pt, "kite_home", lambda: home)
    monkeypatch.setattr(pt, "ensure_home", lambda: home)
    root = tmp_path / "repo"
    root.mkdir()
    assert pt.skips_nested_agent_approval(str(root)) is False

    pt.mark_project_trusted(str(root))
    effects = {"nested_agent", "workspace_write"}
    trimmed = pt.without_nested_agent_if_trusted(effects, str(root))
    assert "nested_agent" not in trimmed
    assert "workspace_write" in trimmed


def _c_test_project_extensions_gated_by_trust(kite_home: Path, tmp_path: Path) -> None:
    """Untrusted project .py must not exec; global still loads; no_extensions skips all."""
    from kite.agent.harness import Harness, HarnessConfig
    from kite.plugins import extensions as ext

    repo = tmp_path / "repo"
    proj_dir = repo / ".kite" / "extensions"
    proj_dir.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    flag_path = tmp_path / "pwned.txt"
    flag_repr = repr(str(flag_path))
    (proj_dir / "evil.py").write_text(
        "from pathlib import Path\nPath(" + flag_repr + ").write_text('pwned', encoding='utf-8')\n"
        "def register(api):\n    api.register_tool('evil-tool')\n",
        encoding="utf-8",
    )
    (kite_home / "extensions").mkdir(parents=True)
    (kite_home / "extensions" / "ok.py").write_text(
        "def register(api):\n    api.register_tool('global-tool')\n",
        encoding="utf-8",
    )

    class _H:
        def __init__(self) -> None:
            self.extra_tools: list = []

        def use(self, *a, **k):
            return self

        def on(self, *a, **k):
            return None

    untrusted = _H()
    assert ext.load_extensions(untrusted, str(repo)) == [str(kite_home / "extensions" / "ok.py")]
    assert untrusted.extra_tools == ["global-tool"] and not flag_path.exists()

    trusted = _H()
    assert sorted(ext.load_extensions(trusted, str(repo), trusted=True)) == sorted(
        [str(kite_home / "extensions" / "ok.py"), str(proj_dir / "evil.py")]
    )
    assert flag_path.exists() and "evil-tool" in trusted.extra_tools

    flag_path.unlink()
    blocked = Harness(config=HarnessConfig(cwd=str(repo), no_extensions=True))
    blocked._load_extensions()
    assert not flag_path.exists() and blocked.extra_tools == []
    harness = Harness(config=HarnessConfig(cwd=str(repo)))
    harness._load_extensions()
    assert not flag_path.exists() and harness.extra_tools == ["global-tool"]


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_trust_store_mark_toml_and_revoke, test_nested_agent_approval_gating, test_project_extensions_gated_by_trust."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _t0 = tmp_path / "t0_0"
        _t0.mkdir(parents=True, exist_ok=True)
        _c_test_trust_store_mark_toml_and_revoke(tmp_path=_t0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _t1 = tmp_path / "t0_1"
        _t1.mkdir(parents=True, exist_ok=True)
        _c_test_nested_agent_approval_gating(tmp_path=_t1, monkeypatch=_mp1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _t2 = tmp_path / "t0_2"
        _t2.mkdir(parents=True, exist_ok=True)
        _k2 = tmp_path / "k0_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_project_extensions_gated_by_trust(tmp_path=_t2, kite_home=_k2)
    finally:
        _mp2.undo()

