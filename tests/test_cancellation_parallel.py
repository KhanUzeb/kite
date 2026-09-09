"""Cancellation and parallel read-only tool execution tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from kite.agent.cancel import CancelToken
from kite.agent.loop import DefaultAgent
from kite.agent.mode import PARALLEL_SAFE_TOOLS
from kite.env.local import LocalEnvironment
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


def _sleep_cmd(seconds: float) -> str:
    # Bash tool runs inside a POSIX shell (Git Bash on Windows).
    return f"sleep {seconds}"


def test_parallel_safe_tools_subset_of_readonly():
    from kite.agent.mode import READONLY_TOOLS

    assert PARALLEL_SAFE_TOOLS.issubset(READONLY_TOOLS)


def test_bash_honours_cancel_token(workspace: Path):
    cancel = CancelToken()
    tools = make_coding_tools(cwd=str(workspace), cancel=cancel, enabled=["bash"], timeout=30)
    env = LocalEnvironment(registry=ToolRegistry(tools))

    def _cancel_soon():
        time.sleep(0.3)
        cancel.request()

    threading.Thread(target=_cancel_soon, daemon=True).start()
    out = env.execute({"tool": "bash", "arguments": {"command": f"{_sleep_cmd(5)} && echo done"}})
    assert out.get("cancelled") is True
    assert out["ok"] is False


def test_parallel_reads_execute(workspace: Path):
    src = workspace / "src"
    (src / "b.py").write_text("y = 2\n", encoding="utf-8")
    tools = make_coding_tools(cwd=str(workspace), enabled=["read"])
    env = LocalEnvironment(registry=ToolRegistry(tools))
    model = MagicMock()
    model.format_observation_messages.return_value = [{"role": "user", "content": "ok"}]
    agent = DefaultAgent(model, env, step_limit=5, cost_limit=1.0)
    message = {
        "role": "assistant",
        "content": "",
        "extra": {
            "actions": [
                {"tool": "read", "arguments": {"path": str(src / "app.py")}},
                {"tool": "read", "arguments": {"path": str(src / "b.py")}},
            ]
        },
    }
    agent.execute_actions(message)
    assert model.format_observation_messages.call_count == 1
    outputs = model.format_observation_messages.call_args[0][1]
    assert len(outputs) == 2
    assert all(o.get("ok") for o in outputs)


def test_request_interrupt_sets_cancel_token():
    cancel = CancelToken()
    model = MagicMock()
    env = MagicMock()
    agent = DefaultAgent(model, env, cancel=cancel)
    agent.request_interrupt()
    assert cancel.is_set() is True
