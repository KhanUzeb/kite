"""Opt-in process, rendering, turn-loop and 20k-file workspace measurements."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kite.bench.suite import BenchmarkResult, _sample
from kite.bench.timing import measure_many


def _cold_process(name: str, args: list[str]) -> BenchmarkResult:
    def run() -> None:
        subprocess.run([sys.executable, *args], check=True, capture_output=True, timeout=30)

    _, sample = measure_many(name, run, iterations=5)
    return _sample(name, "startup", sample, process_cold=True, filesystem_cache="warm/OS-managed")


def _stream_render(width: int) -> BenchmarkResult:
    from rich.console import Console

    from kite.agent.events import Event
    from kite.ui.render import RunDisplay
    from kite.ui.state import SessionUiState
    from kite.ui.style import KITE_THEME

    text = ("A streamed paragraph with **emphasis** and `code` explains the change.\n\n" * 40)
    events = [Event("agent_start", payload={"task": "explain", "provider": "bench", "model": "stub"}),
              Event("stream_start", payload={})]
    events.extend(Event("stream_delta", payload={"text": text[i:i + 17]}) for i in range(0, len(text), 17))
    events.extend([Event("stream_end", payload={}), Event("turn_end", payload={}), Event("agent_end", payload={})])

    def run() -> int:
        output = io.StringIO()
        display = RunDisplay(Console(file=output, width=width, force_terminal=True, theme=KITE_THEME),
                             state=SessionUiState(), quiet=False)
        for event in events:
            display(event)
        return output.tell()

    chars, sample = measure_many("stream_render", run, iterations=5)
    return _sample(f"stream_render_{width}", "ui", sample, columns=width, events=len(events), output_chars=chars)


def _agent_turn(cwd: Path) -> BenchmarkResult:
    from kite.agent.loop import DefaultAgent
    from kite.env.local import LocalEnvironment
    from kite.models.litellm_model import LitellmModel
    from kite.providers.resolve import resolve_model

    class SubmitModel(LitellmModel):
        def query(self, messages: list[dict]) -> dict:
            return {"role": "assistant", "content": "", "extra": {"cost": 0.0, "actions": [
                {"tool": "submit", "id": "bench-submit", "arguments": {"message": "bench complete"}}
            ]}}

    model = SubmitModel(resolve_model(provider="openai", model="gpt-4o-mini"))
    env = LocalEnvironment(cwd=str(cwd))

    def run() -> None:
        result = DefaultAgent(model, env, step_limit=2).run("Reply with a short greeting")
        if result.get("exit_status") != "Submitted":
            raise RuntimeError(f"benchmark turn did not submit: {result}")

    _, sample = measure_many("agent_turn", run, iterations=10)
    return _sample("agent_turn", "agent", sample, model="deterministic stub", turns=1)


def _large_workspace(cwd: Path) -> list[BenchmarkResult]:
    from prompt_toolkit.document import Document

    from kite.context.repomap import build_repo_map
    from kite.env.local import LocalEnvironment
    from kite.ui.complete import SlashCompleter

    root = cwd / "large"
    root.mkdir()
    # A wide directory stresses completion's sort/stat work as well as discovery.
    for i in range(20_000):
        (root / f"module_{i:05}.py").write_text(f"def symbol_{i}():\n    return {i}\n", encoding="utf-8")
    env = LocalEnvironment(cwd=str(root))
    completer = SlashCompleter(lambda: None)  # @path completion never needs the slash index.
    document = Document(f"@{root}/module_19")

    def grep() -> dict:
        result = env.execute({"tool": "grep", "arguments": {"pattern": "symbol_19999", "path": str(root)}})
        if not result.get("ok"):
            raise RuntimeError(f"large grep failed: {result}")
        return result

    rows = []
    for name, fn in (
        ("large_repo_map", lambda: build_repo_map(root, prefer_git_changed=False)),
        ("large_grep", grep),
        ("large_completion", lambda: list(completer.get_completions(document, None))),
    ):
        _, sample = measure_many(name, fn, iterations=5)
        rows.append(_sample(name, "workspace", sample, files=20_000, layout="flat-python"))
    return rows


def _prompt_cache_growth(turns: int) -> BenchmarkResult:
    from kite.models.cache import PromptCacheManager

    def run() -> None:
        manager = PromptCacheManager(provider="anthropic")
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "# Setup context"}]
        for turn in range(turns):
            messages = [*messages, {"role": "assistant", "content": f"read {turn}"},
                        {"role": "tool", "content": "source " * 600}]
            prepared = manager.prepare(messages)
            if len(prepared) != len(messages):
                raise RuntimeError("prompt cache dropped conversation history")

    _, sample = measure_many("prompt_cache_growth", run, iterations=21)
    return _sample(f"prompt_cache_growth_{turns}", "context", sample, turns=turns, observation_bytes=4200)


def _agent_loop(turns: int) -> BenchmarkResult:
    from kite.agent.hooks import HookBus
    from kite.agent.loop import DefaultAgent

    observation = "def example(): return 'source text'\n" * 120

    class StubModel:
        resolved = SimpleNamespace(provider="stub", model="stub")

        def __init__(self) -> None:
            self.calls = 0

        def format_message(self, role, content="", extra=None, **kwargs):
            return {"role": role, "content": content, "extra": extra or {}, **kwargs}

        def query(self, messages):
            self.calls += 1
            if self.calls > turns:
                return self.format_message("assistant", "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nRead complete.")
            args = {"path": f"src/file_{self.calls}.py"}
            call_id = str(self.calls)
            return self.format_message("assistant", "Inspecting source. " * 20,
                extra={"actions": [{"tool": "read", "arguments": args, "id": call_id}], "cost": 0.0},
                tool_calls=[{"id": call_id, "type": "function",
                             "function": {"name": "read", "arguments": json.dumps(args)}}])

        def format_observation_messages(self, message, outputs, template_vars=None):
            return [self.format_message("tool", output["output"], tool_call_id=action["id"], name=action["tool"])
                    for action, output in zip(message["extra"]["actions"], outputs, strict=True)]

    class StubEnv:
        def execute(self, action, cwd=""):
            return {"ok": True, "output": observation}

    def run() -> None:
        agent = DefaultAgent(StubModel(), StubEnv(), system_prompt="Coding instructions. " * 100,
                             instance_prompt="{task}", context_window=2_000_000, step_limit=turns + 2,
                             hooks=HookBus(), on_event=lambda event: None)
        result = agent.run("Inspect the source files")
        if result.get("exit_status") != "Submitted":
            raise RuntimeError(f"benchmark loop did not submit: {result}")

    _, sample = measure_many("agent_loop", run, iterations=7)
    return _sample(f"agent_loop_{turns}", "agent", sample, tool_turns=turns,
                   observation_bytes=len(observation), ms_per_tool_turn=sample.ms / turns)


def _stream_volume(kind: str) -> BenchmarkResult:
    from rich.console import Console

    from kite.agent.events import Event
    from kite.ui.render import RunDisplay
    from kite.ui.state import SessionUiState
    from kite.ui.style import KITE_THEME

    events = [Event(kind, payload={"text": "word "}) for _ in range(20_000)]

    def run() -> None:
        display = RunDisplay(Console(file=io.StringIO(), width=80, height=40, force_terminal=True, theme=KITE_THEME),
                             state=SessionUiState())
        display.state.busy = kind == "stream_reasoning"
        for event in events:
            display(event)
        display.close()

    _, sample = measure_many(kind, run, iterations=3)
    return _sample(f"{kind}_20k", "ui", sample, events=len(events), chars_per_event=5,
                   reasoning_accumulation_only=kind == "stream_reasoning")


def _picker_navigation() -> BenchmarkResult:
    from rich.console import Console

    from kite.ui import pick
    from kite.ui.style import KITE_THEME

    items = [(f"model-{i}", f"Model {i}") for i in range(10_000)]

    def run() -> None:
        events = iter(["m", *(["down"] * 100), "enter"])
        with patch.object(pick, "_event_reader", lambda drawn: lambda: next(events)), redirect_stderr(io.StringIO()):
            pick._raw_pick(Console(file=io.StringIO(), width=80, height=30, theme=KITE_THEME), items,
                           current=None, title="Models", noun="model", show=20, refreshable=False)

    with patch.object(pick, "_ensure_vt_output", lambda: None), patch.object(pick, "_screen_height", lambda: 30):
        _, sample = measure_many("picker_navigation", run, iterations=3)
    return _sample("picker_navigation_10k", "ui", sample, options=10_000, down_keys=100)


def run_full_suite(cwd: Path) -> list[BenchmarkResult]:
    from kite.bench.sessions import run_session_suite

    rows = [
        _cold_process("cold_cli_help", ["-m", "kite.cli.run", "--help"]),
        _cold_process("cold_repl_import", ["-c", "import kite.ui.repl"]),
        *(_stream_render(width) for width in (50, 80, 120)),
        _stream_volume("stream_delta"),
        _stream_volume("stream_reasoning"),
        _picker_navigation(),
        _agent_turn(cwd),
        *(_prompt_cache_growth(turns) for turns in (50, 200)),
        *(_agent_loop(turns) for turns in (50, 200)),
    ]
    rows.extend(_large_workspace(cwd))
    with patch.dict(os.environ, {"TERM": "dumb"}):
        dumb = _stream_render(60)
        rows.append(BenchmarkResult("stream_render_dumb", dumb.category, dumb.seconds, dumb.iterations,
                                    {**dumb.metadata, "term": "dumb", "explicit_height": False}))
    rows.extend(run_session_suite(cwd))
    return rows
