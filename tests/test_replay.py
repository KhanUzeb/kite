"""Replay harness tests."""

from __future__ import annotations

from pathlib import Path

from kite.eval import ReplayBundle, config_hash, run_replay, workspace_fingerprint


def test_replay_bundle_roundtrip(tmp_path: Path) -> None:
    bundle = ReplayBundle(
        run_id="r1",
        prompt_hash="abc",
        context_snapshot_id="snap1",
        config_hash=config_hash({"model": "fake"}),
        model="fake",
        provider="fake",
        tool_catalog_hash="tools",
        workspace_fingerprint="ws",
        responses=[{"role": "assistant", "content": "replayed answer"}],
    )
    path = tmp_path / "bundle.json"
    bundle.save(path)
    loaded = ReplayBundle.load(path)
    assert loaded.run_id == "r1"
    assert len(loaded.responses) == 1


def test_run_replay_without_live_provider() -> None:
    bundle = ReplayBundle(
        run_id="r2",
        prompt_hash="x",
        context_snapshot_id="s",
        config_hash="c",
        model="fake",
        provider="fake",
        tool_catalog_hash="t",
        workspace_fingerprint="w",
        responses=[{"role": "assistant", "content": "done"}],
    )
    out = run_replay(bundle)
    assert out["ok"]
    assert out["content"] == "done"
    assert out["responses_used"] == 1


def test_workspace_fingerprint(workspace: Path) -> None:
    fp = workspace_fingerprint(workspace)
    assert len(fp) == 16
