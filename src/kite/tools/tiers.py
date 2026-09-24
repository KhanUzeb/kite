"""Tool tiers (§3): static core + discoverable offloaded tools behind a flag.

Tool schemas ride along on every request. Most tools beyond the core set are
each needed in under 20% of conversations — moving them out of static context
cut tool-description tokens 60% in the guide's figures (46.9% total in
sessions using integration tools).

- Keep static: high-frequency coding tools (read, grep, glob, ls, edit, bash),
  tools the model calls even when absent, and mode-dependent tools (submit).
- Offload: web/integration, memory, skill install paths, subagent crews, task
  fan-out — left as a name + one-line pointer in the setup message, with full
  schemas discoverable via the `tool_help` pointer grouped by family.
- Pick the split by testing configurations and tracking tokens, cost, latency,
  tool-call errors, and task success (§8). Default off until validated.
"""

from __future__ import annotations

CORE_TOOLS = frozenset({"read", "grep", "glob", "ls", "edit", "write", "bash", "todo_write", "todo_read", "submit"})

OFFLOAD_GROUPS: dict[str, tuple[str, ...]] = {
    "web": ("webfetch", "websearch", "webcrawl"),
    "agents": ("subagent", "task"),
    "memory": ("memory", "skill"),
    "workspace": ("set_cwd",),
}

OFFLOAD_BLURBS: dict[str, str] = {
    "webfetch": "fetch one http(s) URL as text",
    "websearch": "web search → urls then fetch",
    "webcrawl": "crawl a site from a seed URL",
    "subagent": "spawn nested worker(s) with bundled profiles",
    "task": "bounded code search (glob+grep summary)",
    "memory": "list/remember/forget durable notes",
    "skill": "load a named skill",
    "set_cwd": "move session working directory",
}


def partition_tools(names: list[str], *, enabled: bool = False) -> tuple[list[str], list[str]]:
    """Split tool names into (static, offloaded). Disabled by default (flag)."""
    if not enabled:
        return list(names), []
    static = [n for n in names if n in CORE_TOOLS]
    offloaded = [n for n in names if n not in CORE_TOOLS]
    return static, offloaded


def offload_manifest(offloaded: list[str]) -> str:
    """One-line pointers for the setup message; full schemas load as a group."""
    if not offloaded:
        return ""
    grouped: dict[str, list[str]] = {}
    for name in offloaded:
        family = next((fam for fam, members in OFFLOAD_GROUPS.items() if name in members), "other")
        grouped.setdefault(family, []).append(name)
    lines = ["Offloaded tools (not in static context; ask for the group to load it):"]
    for family in sorted(grouped):
        members = ", ".join(f"{n} ({OFFLOAD_BLURBS.get(n, 'tool')})" for n in sorted(grouped[family]))
        lines.append(f"- {family}: {members}")
    return "\n".join(lines)
