"""Cache, venv, discovery, compaction, replay, retry, and relay behavior."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kite.agent.tool_result import ToolResult
from kite.context.discovery import MAX_INSTRUCTION_FILE_CHARS, discover_agents_files
from kite.context.window import ContextUsage, should_compact
from kite.env.venv import apply_venv, discover_venv, prepare_child_env
from kite.eval import ReplayBundle, config_hash
from kite.models.retry import is_transient_provider_error, retry_delay_s
from kite.models.tool_args import repair_tool_arguments
from kite.util.cache import TtlCache


def test_ttl_cache_reuses_evicts_and_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 100.0
    monkeypatch.setattr("kite.util.cache.time", SimpleNamespace(monotonic=lambda: now))
    cache: TtlCache[str, list[int]] = TtlCache(60.0, maxsize=2)
    first = cache.get_or_set("k", lambda: [1])
    assert cache.get_or_set("k", lambda: [2]) is first
    cache.set("a", [1])
    cache.set("b", [2])
    cache.set("c", [3])
    assert cache.get("a") is None
    assert cache.get("b") == [2]
    assert cache.get("c") == [3]

    short: TtlCache[str, str] = TtlCache(10.0)
    short.set("k", "a")
    now = 109.0
    assert short.get_or_set("k", lambda: "b") == "a"
    now = 110.0
    assert short.get_or_set("k", lambda: "b") == "b"


def test_discovery_venv_and_compaction(workspace: Path) -> None:
    root = workspace
    (root / "AGENTS.md").write_text("root agents", encoding="utf-8")
    sub = root / "pkg"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("nested agents", encoding="utf-8")
    files = discover_agents_files(sub)
    assert [Path(f.path).name for f in files] == ["AGENTS.md", "AGENTS.md"]
    assert [f.content for f in files] == ["root agents", "nested agents"]
    (root / "KITE.md").write_text("x" * (MAX_INSTRUCTION_FILE_CHARS + 500), encoding="utf-8")
    huge = discover_agents_files(root)
    kite = next(f for f in huge if Path(f.path).name == "KITE.md")
    assert len(kite.content) <= MAX_INSTRUCTION_FILE_CHARS
    venv = root / ".venv"
    bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    bindir.mkdir(parents=True)
    (bindir / ("python.exe" if sys.platform == "win32" else "python")).write_text("", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    assert discover_venv(root) == venv.resolve()
    env = apply_venv({"PATH": "/usr/bin"}, venv)
    path_value = env.get("Path", env.get("PATH", ""))
    assert str(bindir.resolve()) in path_value
    off = prepare_child_env(cwd=root, auto_venv=False)
    on = prepare_child_env(cwd=root, auto_venv=True)
    assert on.get("VIRTUAL_ENV") == str(venv.resolve())
    assert off.get("VIRTUAL_ENV") != str(venv.resolve())
    usage = ContextUsage(total_tokens=102_400, system_tokens=1000, message_tokens=101_400, tool_tokens=0, message_count=10, window=128_000)
    assert should_compact(usage, ratio=0.80) and not should_compact(usage, ratio=0.85)


def test_replay_retry_and_tool_arguments(tmp_path: Path) -> None:
    bundle = ReplayBundle(run_id="r1", prompt_hash="abc", context_snapshot_id="snap1", config_hash=config_hash({"model": "fake"}), model="fake", provider="fake", tool_catalog_hash="tools", workspace_fingerprint="ws", responses=[{"role": "assistant", "content": "replayed answer"}])
    path = tmp_path / "bundle.json"
    bundle.save(path)
    assert ReplayBundle.load(path) == bundle
    assert is_transient_provider_error(TimeoutError("connection timed out"))
    assert not is_transient_provider_error(ValueError("invalid api key"))
    assert retry_delay_s(1) == 2.0 and retry_delay_s(5) == 30.0
    args, err = repair_tool_arguments('{"path": "a.py"}')
    assert err is None and args == {"path": "a.py"}
    fenced, ferr = repair_tool_arguments('```json\n{"command": "ls"}\n```')
    assert ferr is None and fenced == {"command": "ls"}
    trailing, _ = repair_tool_arguments('{"a": 1,}')
    assert trailing == {"a": 1}
    bad, berr = repair_tool_arguments("not json at all {{{")
    assert bad is None and berr
    payload = {"ok": True, "output": "hello", "path": "/tmp/x", "metadata": {"duration_ms": 12}}
    result = ToolResult.from_dict(payload)
    restored = ToolResult.from_dict(result.to_dict())
    assert restored.to_dict() == result.to_dict()
    assert restored.output == "hello"
    assert restored.metadata["duration_ms"] == 12


def test_orca_relay_detection_and_width(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.util.tty import ORCA_RELAY_MARKERS, RELAY_WIDTH, is_orca_relay, relay_width

    for var in (*ORCA_RELAY_MARKERS, "KITE_COMPACT_UI"):
        monkeypatch.delenv(var, raising=False)
    assert is_orca_relay() is False
    assert relay_width(120) == 120

    monkeypatch.setenv("ORCA_CLI_COMMAND", "orca")
    assert is_orca_relay() is True
    assert relay_width(120) == RELAY_WIDTH
    assert relay_width(40) == 40

    # Explicit override wins both ways.
    monkeypatch.setenv("KITE_COMPACT_UI", "0")
    assert is_orca_relay() is False
    monkeypatch.setenv("KITE_COMPACT_UI", "1")
    assert is_orca_relay() is True


def test_relay_narrows_pick_list_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.ui.credentials import render_pick_list
    from kite.ui.state import SessionUiState
    from kite.ui.status import _terminal_compact, status_segments
    from kite.util.tty import ORCA_RELAY_MARKERS

    long_label = "x" * 80
    for var in (*ORCA_RELAY_MARKERS, "KITE_COMPACT_UI"):
        monkeypatch.delenv(var, raising=False)
    full = render_pick_list([("a", long_label)], title="t", noun="item").plain
    assert long_label[:63] in full and long_label not in full

    monkeypatch.setenv("KITE_COMPACT_UI", "1")
    narrow = render_pick_list([("a", long_label)], title="t", noun="item").plain
    assert long_label[:40] not in narrow and "…" in narrow
    assert _terminal_compact() is True
    state = SessionUiState(model="m", provider="p")
    texts = [text for text, _ in status_segments(state)]
    assert not any(t.startswith("ctx ") for t in texts)
