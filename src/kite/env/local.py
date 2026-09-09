"""Local environment: dispatch tool calls (tau tools) via one registry.

Swap this class for DockerEnvironment later — same execute(action) contract
as mini-swe-agent, so sandboxing stays a one-file change.
"""

from __future__ import annotations

from typing import Any

from kite.agent.exceptions import Submitted
from kite.agent.tool_result import ToolResult
from kite.tools import ToolRegistry
from kite.tools.coding import make_coding_tools


class LocalEnvironment:
    def __init__(
        self,
        cwd: str | None = None,
        timeout: int = 30,
        registry: ToolRegistry | None = None,
        *,
        execution=None,
    ):
        self.cwd = cwd
        self.timeout = timeout
        self.registry = registry or ToolRegistry(make_coding_tools(cwd=cwd, timeout=timeout))
        self.execution = execution

    def execute(self, action: dict) -> dict[str, Any]:
        """action = {"tool": name, "arguments": {...}} or {"command": "..."} for bash-compat."""
        if "command" in action and "tool" not in action:
            action = {"tool": "bash", "arguments": {"command": action["command"]}}

        name = action.get("tool") or action.get("name")
        args = action.get("arguments") or action.get("args") or {}
        tool = self.registry.get(str(name))
        if tool is None:
            return {"ok": False, "error": f"unknown tool: {name}", "output": ""}

        try:
            result = tool.run(dict(args))
        except Submitted:
            raise
        except Exception as e:
            # Windows open() on a directory is PermissionError; keep it a tool
            # result so the agent can recover instead of aborting the run.
            return {"ok": False, "error": str(e), "output": str(e)}
        if result.get("submitted"):
            raise Submitted(
                {
                    "role": "exit",
                    "content": result.get("submission", ""),
                    "extra": {"exit_status": "Submitted", "submission": result.get("submission", "")},
                }
            )
        # Normalize observation shape for the model layer
        if "output" not in result:
            result = {**result, "output": result.get("error") or str(result)}
        return ToolResult.normalize(result, tool=str(name))
