"""Tool registry — tau-style typed tools, mini-style sync execution."""

from __future__ import annotations

from typing import Any, Callable

from kite.tools.metadata import ToolMetadata, metadata_for


class Tool:
    """A tool is a name + JSON schema + sync executor returning a result dict."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        execute_fn: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        metadata: ToolMetadata | None = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._execute_fn = execute_fn
        self.metadata = metadata or metadata_for(name)

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._execute_fn(arguments)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        self._schema_cache: list[dict[str, Any]] | None = None
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._schema_cache = None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def openai_schemas(self) -> list[dict[str, Any]]:
        if self._schema_cache is None:
            self._schema_cache = [t.schema() for t in self._tools.values()]
        return self._schema_cache
