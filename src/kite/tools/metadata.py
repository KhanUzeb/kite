"""Tool scheduling metadata — used by the executor for parallelism and policy."""

from __future__ import annotations

from dataclasses import dataclass

from kite.agent.mode import MUTATING_TOOLS, READONLY_TOOLS


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    read_only: bool = False
    mutating: bool = False
    network: bool = False
    concurrency_safe: bool = False
    expensive: bool = False
    cancellable: bool = False


def _meta(
    *,
    read_only: bool = False,
    mutating: bool = False,
    network: bool = False,
    concurrency_safe: bool = False,
    expensive: bool = False,
    cancellable: bool = False,
) -> ToolMetadata:
    return ToolMetadata(
        read_only=read_only,
        mutating=mutating,
        network=network,
        concurrency_safe=concurrency_safe,
        expensive=expensive,
        cancellable=cancellable,
    )


DEFAULT_TOOL_METADATA: dict[str, ToolMetadata] = {
    "read": _meta(read_only=True, concurrency_safe=True),
    "grep": _meta(read_only=True, concurrency_safe=True),
    "glob": _meta(read_only=True, concurrency_safe=True),
    "ls": _meta(read_only=True, concurrency_safe=True),
    "skill": _meta(read_only=True),
    "todo_read": _meta(read_only=True),
    "memory": _meta(read_only=True),
    "webfetch": _meta(read_only=True, network=True, expensive=True),
    "websearch": _meta(read_only=True, network=True, expensive=True),
    "webcrawl": _meta(read_only=True, network=True, expensive=True),
    "context7_resolve": _meta(read_only=True, network=True, expensive=True),
    "context7_docs": _meta(read_only=True, network=True, expensive=True),
    "subagent": _meta(read_only=True, expensive=True),
    "task": _meta(read_only=True, expensive=True),
    "write": _meta(mutating=True),
    "edit": _meta(mutating=True),
    "todo_write": _meta(mutating=True),
    "bash": _meta(mutating=True, cancellable=True, expensive=True),
}


def metadata_for(name: str) -> ToolMetadata:
    if name in READONLY_TOOLS:
        base = DEFAULT_TOOL_METADATA.get(name, _meta(read_only=True))
        if not base.read_only:
            return _meta(read_only=True, concurrency_safe=base.concurrency_safe, network=base.network)
        return base
    if name in MUTATING_TOOLS:
        return DEFAULT_TOOL_METADATA.get(name, _meta(mutating=True))
    return DEFAULT_TOOL_METADATA.get(name, _meta())
