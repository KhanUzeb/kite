"""Minimal MCP stdio client — discover and register external tools."""

from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from typing import Any

from kite.tools import Tool


class McpClient:
    """JSON-RPC over stdio to an MCP server subprocess."""

    def __init__(self, command: list[str], *, name: str = "mcp") -> None:
        self.name = name
        self.command = command
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._id = 0

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kite", "version": "0.6"},
            },
        )
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
        self._proc = None

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            return
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _request(self, method: str, params: dict[str, Any], *, timeout: float = 15.0) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("MCP process not started")
        with self._lock:
            self._id += 1
            req_id = self._id
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                line = self._proc.stdout.readline()
                if not line:
                    break
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if resp.get("id") == req_id:
                    if "error" in resp:
                        raise RuntimeError(str(resp["error"]))
                    return resp.get("result") or {}
            raise TimeoutError(f"MCP {method} timed out")

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools") or []
        return tools if isinstance(tools, list) else []


def mcp_tool_to_kite(client: McpClient, spec: dict[str, Any]) -> Tool:
    name = str(spec.get("name") or "mcp_tool")
    description = str(spec.get("description") or f"MCP tool {name}")
    schema = spec.get("inputSchema") or {"type": "object", "properties": {}}
    prefix = client.name

    def execute(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = client._request("tools/call", {"name": name, "arguments": args})
            content = result.get("content") or []
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            text = "\n".join(parts) or json.dumps(result, default=str)[:8000]
            return {"ok": not result.get("isError"), "output": text}
        except Exception as e:
            return {"ok": False, "error": str(e), "output": str(e)}

    return Tool(
        name=f"mcp_{prefix}_{name}".replace("-", "_")[:64],
        description=f"[MCP:{prefix}] {description}",
        parameters=schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
        execute_fn=execute,
    )


def load_mcp_tools(servers: list[dict[str, Any]]) -> tuple[list[Tool], list[McpClient]]:
    """Start configured MCP servers and return Kite tools + live clients (caller must close)."""
    tools: list[Tool] = []
    clients: list[McpClient] = []
    for srv in servers:
        if not srv.get("enabled", True):
            continue
        name = str(srv.get("name") or uuid.uuid4().hex[:8])
        command = srv.get("command")
        if not command:
            continue
        if isinstance(command, str):
            command = command.split()
        args = list(srv.get("args") or [])
        full = [str(c) for c in command] + [str(a) for a in args]
        client = McpClient(full, name=name)
        try:
            client.start()
            for spec in client.list_tools():
                tools.append(mcp_tool_to_kite(client, spec))
            clients.append(client)
        except Exception:
            client.close()
    return tools, clients
