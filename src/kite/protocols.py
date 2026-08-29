"""Duck-typed protocols. Ignore unless you want static checking."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class Model(Protocol):
    def query(self, messages: list[dict]) -> dict: ...

    def format_message(self, **kwargs) -> dict: ...

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]: ...


class Environment(Protocol):
    def execute(self, action: dict, cwd: str = "") -> dict[str, Any]: ...


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]: ...


class Agent(Protocol):
    def run(self, task: str, **kwargs) -> dict: ...

    def save(self, path: Path | None) -> dict: ...
