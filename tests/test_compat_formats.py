"""Compatibility tests for 0.8 formats and extension points (Milestone A)."""

from __future__ import annotations

import json
from pathlib import Path

from kite.agent.harness import Harness, HarnessConfig
from kite.extensions.loader import ExtensionAPI, extension_dirs
from kite.memory.session import create_session, load_session


def test_jsonl_session_roundtrip(kite_home) -> None:
    session = create_session(task="compat", cwd="/tmp", provider="groq", model="test")
    session.record_event("turn_start", {"n": 1})
    session.record_event("compact", {"ratio": 0.5})

    loaded = load_session(session.id)
    assert loaded.meta.task == "compat"
    assert loaded.meta.provider == "groq"

    path = session.path or session._session_path()
    kinds = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("type") == "event":
                kinds.append(row["kind"])
    assert "turn_start" in kinds


def test_harness_config_fields_stable() -> None:
    """HarnessConfig public fields remain available for extensions."""
    cfg = HarnessConfig(
        provider="x",
        model_name="y",
        no_extensions=True,
        execution_mode="restricted",
    )
    h = Harness(config=cfg)
    assert h.config.no_extensions is True
    assert h.config.execution_mode == "restricted"


def test_extension_api_surface() -> None:
    h = Harness()
    api = ExtensionAPI(h)

    def _hook(_):
        return None

    api.on("before_query", _hook)
    assert "before_query" in h.hooks._subs  # noqa: SLF001 — contract test


def test_extension_dirs_include_project_kite(workspace: Path) -> None:
    ext = workspace / ".kite" / "extensions"
    ext.mkdir(parents=True)
    dirs = extension_dirs(workspace)
    assert any(d.resolve() == ext.resolve() for d in dirs)
