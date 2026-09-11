"""Config, cache, venv, discovery, version sync, replay, retry, tools."""

from __future__ import annotations

import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from kite.agent.exceptions import ProviderFault
from kite.agent.tool_result import ToolResult
from kite.config.runtime import load_runtime_config
from kite.context.discovery import MAX_INSTRUCTION_FILE_CHARS, discover_agents_files
from kite.context.window import ContextUsage, should_compact
from kite.env.local import LocalEnvironment
from kite.env.venv import apply_venv, discover_venv, prepare_child_env
from kite.eval import ReplayBundle, config_hash, run_replay, workspace_fingerprint
from kite.models.retry import is_transient_provider_error, retry_delay_s
from kite.models.tool_args import repair_tool_arguments
from kite.providers.catalog import load_catalog
from kite.tools import Tool, ToolRegistry
from kite.tools.metadata import metadata_for
from kite.util.cache import TtlCache

ROOT = Path(__file__).resolve().parents[1]


def test_ttl_cache_and_runtime_catalog() -> None:
    cache: TtlCache[str, list[int]] = TtlCache(60.0, maxsize=2)
    first = cache.get_or_set("k", lambda: [1])
    assert cache.get_or_set("k", lambda: [2]) is first
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None and cache.get("c") == 3
    short: TtlCache[str, str] = TtlCache(0.01)
    short.get_or_set("k", lambda: "a")
    time.sleep(0.02)
    assert short.get_or_set("k", lambda: "b") == "b"
    cfg = load_runtime_config()
    assert cfg.prompt_cache_enabled is True and cfg.orchestrator_max_workers >= 1
    assert load_runtime_config() is load_runtime_config()
    assert load_catalog() is load_catalog()


def test_sync_version_markers_and_check() -> None:
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    marker = re.compile(r"^# kite-release-version: ([\d.]+)$", re.MULTILINE)
    for path in sorted((ROOT / "scripts").iterdir()):
        if path.suffix not in {".sh", ".ps1", ".py"}:
            continue
        match = marker.search(path.read_text(encoding="utf-8"))
        assert match and match.group(1) == expected, path.name
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--check"], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    before = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    sync = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_version.py")], cwd=ROOT, capture_output=True, text=True, check=True)
    assert before == (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "already at" in sync.stdout or "updated" in sync.stdout


def test_discovery_venv_and_compaction(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("root agents", encoding="utf-8")
    sub = root / "pkg"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("nested agents", encoding="utf-8")
    files = discover_agents_files(sub)
    assert [Path(f.path).name for f in files].count("AGENTS.md") == 1
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


def test_replay_retry_and_tool_metadata(tmp_path: Path, workspace: Path) -> None:
    bundle = ReplayBundle(run_id="r1", prompt_hash="abc", context_snapshot_id="snap1", config_hash=config_hash({"model": "fake"}), model="fake", provider="fake", tool_catalog_hash="tools", workspace_fingerprint="ws", responses=[{"role": "assistant", "content": "replayed answer"}])
    path = tmp_path / "bundle.json"
    bundle.save(path)
    assert ReplayBundle.load(path).run_id == "r1"
    out = run_replay(ReplayBundle(run_id="r2", prompt_hash="x", context_snapshot_id="s", config_hash="c", model="fake", provider="fake", tool_catalog_hash="t", workspace_fingerprint="w", responses=[{"role": "assistant", "content": "done"}]))
    assert out["ok"] and out["content"] == "done"
    assert len(workspace_fingerprint(workspace)) == 16
    assert is_transient_provider_error(TimeoutError("connection timed out"))
    assert not is_transient_provider_error(ValueError("invalid api key"))
    assert retry_delay_s(1) == 2.0 and retry_delay_s(5) == 30.0
    fault = ProviderFault("network down", attempts=4)
    assert fault.attempts == 4
    args, err = repair_tool_arguments('{"path": "a.py"}')
    assert err is None and args == {"path": "a.py"}
    fenced, ferr = repair_tool_arguments('```json\n{"command": "ls"}\n```')
    assert ferr is None and fenced == {"command": "ls"}
    trailing, _ = repair_tool_arguments('{"a": 1,}')
    assert trailing == {"a": 1}
    bad, berr = repair_tool_arguments("not json at all {{{")
    assert bad is None and berr
    result = ToolResult.from_dict({"ok": True, "output": "hello", "path": "/tmp/x", "metadata": {"duration_ms": 12}})
    assert ToolResult.from_dict(result.to_dict()).output == "hello"
    env_out = LocalEnvironment(cwd=str(workspace)).execute({"tool": "read", "arguments": {"path": str(workspace / "src" / "app.py")}})
    assert env_out["ok"] and env_out.get("summary")
    assert metadata_for("read").read_only is True and metadata_for("bash").mutating is True
    tool = Tool("read", "read file", {"type": "object", "properties": {}}, lambda _a: {"ok": True})
    assert tool.metadata.read_only is True
    assert ToolRegistry([Tool("grep", "grep", {"type": "object", "properties": {}}, lambda _a: {"ok": True})]).get("grep").metadata.concurrency_safe
