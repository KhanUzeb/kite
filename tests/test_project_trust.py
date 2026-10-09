"""Project trust store and approval skip helpers."""

from __future__ import annotations

from pathlib import Path

from kite.guardrails import project_trust as pt


def test_trust_store_mark_toml_and_revoke(kite_home: Path, workspace: Path) -> None:
    root = workspace
    effects = {"nested_agent", "workspace_write"}
    assert pt.is_project_trusted(str(root)) is False
    assert pt.skips_nested_agent_approval(str(root)) is False
    assert pt.without_nested_agent_if_trusted(effects, str(root)) == effects

    pt.mark_project_trusted(str(root))
    assert pt.is_project_trusted(str(root)) is True
    assert pt.without_nested_agent_if_trusted(effects, str(root)) == {"workspace_write"}
    assert effects == {"nested_agent", "workspace_write"}

    assert pt.revoke_project_trust(str(root)) is True
    assert pt.is_project_trusted(str(root)) is False
    assert pt.without_nested_agent_if_trusted(effects, str(root)) == effects

    kite = root / ".kite"
    kite.mkdir(parents=True, exist_ok=True)
    (kite / "project.toml").write_text("[project]\ntrust = true\n", encoding="utf-8")
    assert pt.is_project_trusted(str(root)) is True
    assert pt.skips_nested_agent_approval(str(root)) is True


def test_project_extensions_gated_by_trust(kite_home: Path, workspace: Path, tmp_path: Path) -> None:
    """Untrusted project .py must not exec; global still loads; no_extensions skips all."""
    from kite.agent.harness import Harness, HarnessConfig
    from kite.plugins import extensions as ext

    repo = workspace
    proj_dir = repo / ".kite" / "extensions"
    proj_dir.mkdir(parents=True)
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

