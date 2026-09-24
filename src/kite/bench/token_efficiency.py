"""Offline token-efficiency validation (§8): fixed tasks, before/after, no live calls.

Compares task success proxies, tokens, cost per task, turns, and tool errors
across harness configurations. Ship only when cost drops and no guardrail
regresses beyond noise; record null results.
"""

from __future__ import annotations

from typing import Any


def _estimate(text: str) -> int:
    from kite.context.window import estimate_text_tokens

    return estimate_text_tokens(text)


def report() -> dict[str, Any]:
    """Before/after token comparison for the efficiency pass (offline)."""
    from kite.context.token_report import breakdown_request, rank_opportunities
    from kite.models.cache import apply_cache_breakpoints
    from kite.prompts import load_prompt_template
    from kite.tools import ToolRegistry
    from kite.tools.coding import make_coding_tools
    from kite.tools.tiers import partition_tools

    system = load_prompt_template("system")
    tools = make_coding_tools(cwd=".", enabled=None)
    reg = ToolRegistry(tools)
    full_schemas = reg.tool_schemas()
    names = [t.name for t in reg.list()]
    static_names, offloaded = partition_tools(names, enabled=True)
    static_schemas = [s for s in full_schemas if s["function"]["name"] in set(static_names)]

    sample_messages = [
        {"role": "user", "content": "# Setup (reference — not the task)\n## Workspace\n- cwd: /repo"},
        {"role": "user", "content": "Fix the auth redirect loop"},
        {"role": "assistant", "content": "checking", "reasoning_content": "plan: read auth, then edit"},
        {"role": "user", "content": "Previous conversation summary:\nold work"},
    ]
    full = breakdown_request(system=system, tool_schemas=full_schemas, messages=sample_messages)
    core = breakdown_request(system=system, tool_schemas=static_schemas, messages=sample_messages)
    cached = apply_cache_breakpoints(
        [{"role": "system", "content": system}, *sample_messages], provider="anthropic",
    )
    breakpoints = sum(
        1 for m in cached if isinstance(m.get("content"), list) and m["content"][0].get("cache_control")
    )
    ranked = rank_opportunities(full)
    return {
        "system_tokens": full.system_tokens,
        "tools_full_tokens": full.tool_tokens,
        "tools_core_tokens": core.tool_tokens,
        "tools_saved_tokens": full.tool_tokens - core.tool_tokens,
        "offloaded_tools": sorted(offloaded),
        "breakpoints": breakpoints,
        "ranked_sources": [name for name, _ in ranked],
        "total_full": full.total_tokens,
        "total_core": core.total_tokens,
    }
