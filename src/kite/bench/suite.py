"""Repeatable harness benchmarks — no live provider calls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kite.bench.timing import TimingSample, measure, measure_many


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    name: str
    category: str
    seconds: float
    iterations: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ms(self) -> float:
        return self.seconds * 1000.0

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["ms"] = round(self.ms, 3)
        return row


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    kite_version: str
    python_version: str
    platform: str
    cwd: str
    results: tuple[BenchmarkResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kite_version": self.kite_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "cwd": self.cwd,
            "results": [r.to_dict() for r in self.results],
        }

    def compare(self, baseline: BenchmarkReport) -> list[dict[str, Any]]:
        """Return BEFORE / AFTER / DELTA rows for shared benchmark names."""
        before = {r.name: r for r in baseline.results}
        rows: list[dict[str, Any]] = []
        for after in self.results:
            prev = before.get(after.name)
            if prev is None:
                continue
            delta_ms = after.ms - prev.ms
            pct = ((after.ms / prev.ms) - 1.0) * 100.0 if prev.ms else 0.0
            rows.append(
                {
                    "name": after.name,
                    "category": after.category,
                    "before_ms": round(prev.ms, 3),
                    "after_ms": round(after.ms, 3),
                    "delta_ms": round(delta_ms, 3),
                    "delta_pct": round(pct, 2),
                }
            )
        return rows


def _sample(name: str, category: str, sample: TimingSample, **metadata: Any) -> BenchmarkResult:
    return BenchmarkResult(
        name=name,
        category=category,
        seconds=sample.seconds,
        iterations=sample.iterations,
        metadata=metadata,
    )


def _bench_cli_import() -> BenchmarkResult:
    def _run() -> None:
        if "kite.cli.run" in sys.modules:
            del sys.modules["kite.cli.run"]
        import kite.cli.run  # noqa: F401

    _, sample = measure_many("cli_import", _run, iterations=3)
    return _sample("cli_import", "startup", sample)


def _bench_config_load() -> BenchmarkResult:
    from kite.config import load_runtime_config

    _, sample = measure_many("config_load", load_runtime_config, iterations=5)
    return _sample("config_load", "startup", sample)


def _bench_context_gather(cwd: Path) -> BenchmarkResult:
    import kite.context.discovery as discovery

    def _run():
        discovery._CTX_CACHE.clear()
        gather = discovery.gather_project_context
        gather(cwd, include_git=False)

    _, sample = measure_many("context_gather", _run, iterations=3)
    return _sample("context_gather", "context", sample, files=1)


def _bench_tool_registry(cwd: Path) -> BenchmarkResult:
    from kite.tools import ToolRegistry
    from kite.tools.coding import make_coding_tools

    def _run():
        reg = ToolRegistry(make_coding_tools(cwd=str(cwd)))
        return len(reg.openai_schemas())

    count, sample = measure_many("tool_registry", _run, iterations=5)
    return _sample("tool_registry", "tools", sample, tool_count=count)


def _bench_read_tool(cwd: Path) -> BenchmarkResult:
    from kite.env.local import LocalEnvironment

    env = LocalEnvironment(cwd=str(cwd))
    target = str(cwd / "src" / "app.py")

    def _run():
        return env.execute({"tool": "read", "arguments": {"path": target}})

    out, sample = measure_many("read_tool", _run, iterations=10)
    return _sample("read_tool", "tools", sample, ok=bool(out.get("ok")))


def _bench_grep_tool(cwd: Path) -> BenchmarkResult:
    from kite.env.local import LocalEnvironment

    env = LocalEnvironment(cwd=str(cwd))
    args = {"pattern": "x =", "path": str(cwd / "src")}

    def _run():
        return env.execute({"tool": "grep", "arguments": args})

    out, sample = measure_many("grep_tool", _run, iterations=5)
    return _sample("grep_tool", "tools", sample, ok=bool(out.get("ok")))


def _bench_bash_echo(cwd: Path) -> BenchmarkResult:
    from kite.env.local import LocalEnvironment

    env = LocalEnvironment(cwd=str(cwd))

    def _run():
        return env.execute({"tool": "bash", "arguments": {"command": "echo ok"}})

    out, sample = measure_many("bash_echo", _run, iterations=5)
    return _sample("bash_echo", "tools", sample, ok=bool(out.get("ok")))


def _bench_prompt_assembly(cwd: Path) -> BenchmarkResult:
    from kite.config import load_runtime_config
    from kite.context.discovery import gather_project_context
    from kite.prompts import assemble_system_prompt

    ctx = gather_project_context(cwd, include_git=False)

    def _run():
        return assemble_system_prompt(config=load_runtime_config(), project_context=ctx)

    text, sample = measure("prompt_assembly", _run)
    return _sample("prompt_assembly", "context", sample, chars=len(text))


def _bench_skills_load() -> BenchmarkResult:
    from kite.skills.loader import load_skills

    def _run():
        return len(load_skills())

    count, sample = measure_many("skills_load", _run, iterations=3)
    return _sample("skills_load", "startup", sample, skill_count=count)


def _bench_subprocess_spawn() -> BenchmarkResult:
    def _run():
        proc = subprocess.run(
            [sys.executable, "-c", "print('ok')"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode

    rc, sample = measure_many("subprocess_spawn", _run, iterations=5)
    return _sample("subprocess_spawn", "tools", sample, returncode=rc)


def _ensure_workspace(cwd: Path) -> None:
    src = cwd / "src"
    src.mkdir(parents=True, exist_ok=True)
    app = src / "app.py"
    if not app.is_file():
        app.write_text("x = 1\n", encoding="utf-8")
    if not (cwd / "pyproject.toml").is_file():
        (cwd / "pyproject.toml").write_text("[project]\nname='bench'\n", encoding="utf-8")


def run_suite(*, cwd: str | Path | None = None) -> BenchmarkReport:
    """Run the built-in benchmark suite and return structured results."""
    import platform

    try:
        from kite import __version__
    except Exception:  # pragma: no cover
        __version__ = "unknown"

    root = Path(cwd or os.getcwd()).expanduser().resolve()
    _ensure_workspace(root)

    builders: list[Callable[[], BenchmarkResult]] = [
        _bench_cli_import,
        _bench_config_load,
        _bench_skills_load,
        lambda: _bench_context_gather(root),
        lambda: _bench_tool_registry(root),
        lambda: _bench_read_tool(root),
        lambda: _bench_grep_tool(root),
        lambda: _bench_bash_echo(root),
        lambda: _bench_prompt_assembly(root),
        _bench_subprocess_spawn,
    ]

    results = tuple(builder() for builder in builders)
    return BenchmarkReport(
        kite_version=__version__,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        cwd=str(root),
        results=results,
    )


def load_report(path: str | Path) -> BenchmarkReport:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    results = tuple(
        BenchmarkResult(
            name=r["name"],
            category=r["category"],
            seconds=float(r["seconds"]),
            iterations=int(r.get("iterations", 1)),
            metadata=dict(r.get("metadata") or {}),
        )
        for r in data["results"]
    )
    return BenchmarkReport(
        kite_version=str(data.get("kite_version", "")),
        python_version=str(data.get("python_version", "")),
        platform=str(data.get("platform", "")),
        cwd=str(data.get("cwd", "")),
        results=results,
    )


def save_report(report: BenchmarkReport, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
