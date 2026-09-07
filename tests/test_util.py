"""Config, cache, venv, discovery, version sync, replay, provider retry, tools."""

from __future__ import annotations

import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

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
from kite.tools import Tool, ToolRegistry
from kite.tools.metadata import metadata_for
from kite.util.cache import TtlCache

ROOT = Path(__file__).resolve().parents[1]


# --- cache ---


def test_ttl_cache_hit_returns_same_object() -> None:
    cache: TtlCache[str, list[int]] = TtlCache(60.0)
    first = cache.get_or_set("k", lambda: [1])
    second = cache.get_or_set("k", lambda: [2])
    assert first is second
    assert first == [1]


def test_ttl_cache_evicts_oldest_at_maxsize() -> None:
    cache: TtlCache[str, int] = TtlCache(60.0, maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_ttl_cache_expires() -> None:
    cache: TtlCache[str, str] = TtlCache(0.01)
    first = cache.get_or_set("k", lambda: "a")
    time.sleep(0.02)
    second = cache.get_or_set("k", lambda: "b")
    assert first == "a"
    assert second == "b"


# --- config ---


def test_default_config_loads_trusted_paths_and_cache() -> None:
    cfg = load_runtime_config()
    assert isinstance(cfg.guardrails.trusted_paths, list)
    assert cfg.prompt_cache_enabled is True
    assert cfg.orchestrator_max_workers >= 1
    assert cfg.ui_theme == "auto"
    assert cfg.ui_font == "unicode"


def test_runtime_config_cache_returns_same_object() -> None:
    assert load_runtime_config() is load_runtime_config()


def test_catalog_cache_returns_same_object() -> None:
    from kite.providers.catalog import load_catalog

    assert load_catalog() is load_catalog()


# --- sync_version ---


def test_all_scripts_have_release_marker() -> None:
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    marker = re.compile(r"^# kite-release-version: ([\d.]+)$", re.MULTILINE)
    scripts = ROOT / "scripts"
    for path in sorted(scripts.iterdir()):
        if path.suffix not in {".sh", ".ps1", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        match = marker.search(text)
        assert match, f"{path.name} missing release marker"
        assert match.group(1) == expected, f"{path.name} marker {match.group(1)} != {expected}"


def test_sync_version_check_passes_on_repo() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_sync_version_sync_is_idempotent() -> None:
    before = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    after = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert before == after
    assert "already at" in proc.stdout or "updated" in proc.stdout


# --- discovery ---


def test_discover_agents_dedupes_instruction_basenames(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("root agents", encoding="utf-8")
    sub = root / "pkg"
    sub.mkdir()
    (sub / "AGENTS.md").write_text("nested agents", encoding="utf-8")
    files = discover_agents_files(sub)
    basenames = [Path(f.path).name for f in files]
    assert basenames.count("AGENTS.md") == 1
    assert "root agents" in files[0].content


def test_discover_agents_truncates_large_files(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    huge = "x" * (MAX_INSTRUCTION_FILE_CHARS + 500)
    (root / "KITE.md").write_text(huge, encoding="utf-8")
    files = discover_agents_files(root)
    assert len(files) == 1
    assert len(files[0].content) <= MAX_INSTRUCTION_FILE_CHARS
    assert files[0].content.endswith("...[truncated]...")


# --- venv ---


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


# --- compaction ratio ---


def test_should_compact_at_eighty_percent() -> None:
    usage = ContextUsage(
        total_tokens=102_400,
        system_tokens=1000,
        message_tokens=101_400,
        tool_tokens=0,
        message_count=10,
        window=128_000,
    )
    assert should_compact(usage, ratio=0.80)
    assert not should_compact(usage, ratio=0.85)


# --- replay ---


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


# --- provider retry ---


def test_transient_timeout_and_rate_limit() -> None:
    assert is_transient_provider_error(TimeoutError("connection timed out"))
    assert is_transient_provider_error(RuntimeError("Rate limit exceeded (429)"))
    assert is_transient_provider_error(Exception("503 Service Unavailable"))


def test_non_transient_auth_error() -> None:
    assert not is_transient_provider_error(ValueError("invalid api key"))
    assert not is_transient_provider_error(RuntimeError("model not found"))


def test_retry_delay_exponential() -> None:
    assert retry_delay_s(1) == 2.0
    assert retry_delay_s(2) == 4.0
    assert retry_delay_s(5) == 30.0


def test_provider_fault_carries_attempts() -> None:
    fault = ProviderFault("network down", attempts=4)
    assert fault.error == "network down"
    assert fault.attempts == 4


# --- tool args / result / metadata ---


def test_repair_valid_json() -> None:
    args, err = repair_tool_arguments('{"path": "a.py"}')
    assert err is None
    assert args == {"path": "a.py"}


def test_repair_fenced_json() -> None:
    raw = '```json\n{"command": "ls"}\n```'
    args, err = repair_tool_arguments(raw)
    assert err is None
    assert args == {"command": "ls"}


def test_repair_trailing_comma() -> None:
    args, err = repair_tool_arguments('{"a": 1,}')
    assert err is None
    assert args == {"a": 1}


def test_repair_fails_on_garbage() -> None:
    args, err = repair_tool_arguments("not json at all {{{")
    assert args is None
    assert err


def test_tool_result_roundtrip() -> None:
    raw = {
        "ok": True,
        "output": "hello",
        "path": "/tmp/x",
        "metadata": {"duration_ms": 12},
    }
    result = ToolResult.from_dict(raw)
    again = ToolResult.from_dict(result.to_dict())
    assert again.ok is True
    assert again.output == "hello"
    assert again.data.get("path") == "/tmp/x"


def test_tool_result_normalize_adds_summary(workspace) -> None:
    env = LocalEnvironment(cwd=str(workspace))
    out = env.execute({"tool": "read", "arguments": {"path": str(workspace / "src" / "app.py")}})
    assert out["ok"] is True
    assert out.get("summary")
    assert out.get("metadata", {}).get("tool") == "read"


def test_tool_metadata_defaults() -> None:
    read_meta = metadata_for("read")
    assert read_meta.read_only is True
    assert read_meta.concurrency_safe is True
    bash_meta = metadata_for("bash")
    assert bash_meta.mutating is True
    assert bash_meta.cancellable is True


def test_tool_exposes_metadata() -> None:
    tool = Tool("read", "read file", {"type": "object", "properties": {}}, lambda _a: {"ok": True})
    assert tool.metadata.read_only is True


def test_registry_metadata_lookup() -> None:
    reg = ToolRegistry([Tool("grep", "grep", {"type": "object", "properties": {}}, lambda _a: {"ok": True})])
    tool = reg.get("grep")
    assert tool is not None
    assert tool.metadata.concurrency_safe is True
