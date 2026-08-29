"""MCP client loading — startup warnings."""

from __future__ import annotations

from kite.mcp.client import load_mcp_tools


def test_mcp_bad_server_returns_warning() -> None:
    tools, clients, warnings = load_mcp_tools(
        [{"name": "bad", "command": ["__no_such_mcp_binary__"], "enabled": True}]
    )
    assert tools == []
    assert clients == []
    assert len(warnings) == 1
    assert "bad" in warnings[0]
