"""Visual families for built-in tools — transcript rows and `/tools`."""

from __future__ import annotations

from kite.tools.metadata import metadata_for

# name → (glyph, short tag)
_FAMILIES: dict[str, tuple[str, str]] = {
    "read": ("○", "read"),
    "grep": ("○", "read"),
    "glob": ("○", "read"),
    "ls": ("○", "read"),
    "write": ("✎", "edit"),
    "edit": ("✎", "edit"),
    "bash": ("$", "sh"),
    "set_cwd": ("$", "sh"),
    "todo_write": ("·", "plan"),
    "todo_read": ("·", "plan"),
    "skill": ("◆", "skill"),
    "memory": ("◆", "mem"),
    "webfetch": ("↗", "net"),
    "websearch": ("↗", "net"),
    "webcrawl": ("↗", "net"),
    "context7_resolve": ("↗", "docs"),
    "context7_docs": ("↗", "docs"),
    "gh_issue": ("↗", "gh"),
    "gh_pr": ("↗", "gh"),
    "gh_prs": ("↗", "gh"),
    "gh_runs": ("↗", "gh"),
    "gh_run": ("↗", "gh"),
    "subagent": ("◈", "crew"),
    "task": ("◈", "crew"),
    "submit": ("·", "plan"),
}

TOOL_BLURBS: dict[str, str] = {
    "read": "Bounded file read with optional line numbers",
    "grep": "Search contents (ripgrep) — files_only / count_only save tokens",
    "glob": "Find paths by pattern; sort=mtime for recent first",
    "ls": "List one directory level",
    "write": "Create or overwrite a file — prefer edit for existing files",
    "edit": "Replace an exact string in a file",
    "bash": "Shell command — fresh process; set_cwd or cwd= to move",
    "set_cwd": "Move the session working directory for all tools",
    "todo_write": "Replace the live plan checklist",
    "todo_read": "Read the current plan checklist",
    "submit": "Finish a build-mode task with Done / Changed / Verification",
    "skill": "Load or install a named skill",
    "memory": "List, add, or drop durable notes (not the chat log)",
    "webfetch": "Fetch one URL as extracted text",
    "websearch": "Search the web (keyed engines or DuckDuckGo)",
    "webcrawl": "Crawl from a seed URL — prefer webfetch for one page",
    "context7_resolve": "Resolve a library id for Context7 docs",
    "context7_docs": "Fetch library docs from Context7",
    "gh_issue": "Read a GitHub issue",
    "gh_pr": "Read a GitHub pull request",
    "gh_prs": "List GitHub pull requests",
    "gh_runs": "List GitHub Actions runs",
    "gh_run": "Read one GitHub Actions run",
    "subagent": "Spawn nested workers (scout / reviewer / shell / coder)",
    "task": "Dispatch bounded investigation(s) in parallel",
}

_ORDER = ("read", "edit", "sh", "plan", "skill", "mem", "net", "docs", "gh", "crew")


def tool_cue(name: str) -> tuple[str, str]:
    """Return (glyph, tag) for a built-in tool."""
    key = (name or "").strip().lower()
    if key in _FAMILIES:
        return _FAMILIES[key]
    meta = metadata_for(key)
    if meta.network:
        return "↗", "net"
    if meta.mutating:
        return "✎", "edit"
    if meta.read_only:
        return "○", "read"
    return "·", "tool"


def tool_family_label(tag: str) -> str:
    return {
        "read": "inspect",
        "edit": "edit",
        "sh": "shell",
        "plan": "plan",
        "skill": "skill",
        "mem": "memory",
        "net": "web",
        "docs": "docs",
        "gh": "github",
        "crew": "crew",
        "tool": "other",
    }.get(tag, tag)


def format_tool_catalog(names: list[str] | None = None, *, descriptions: dict[str, str] | None = None) -> str:
    """Grouped `/tools` listing with the same glyphs as the transcript."""
    names = list(names) if names is not None else list(TOOL_BLURBS)
    descriptions = {**TOOL_BLURBS, **(descriptions or {})}
    buckets: dict[str, list[str]] = {}
    for name in names:
        glyph, tag = tool_cue(name)
        desc = (descriptions.get(name) or "").split(". ")[0].strip()
        if desc.endswith("."):
            desc = desc[:-1]
        if len(desc) > 72:
            desc = desc[:69] + "…"
        line = f"  {glyph} {name:<16} {desc}".rstrip()
        buckets.setdefault(tag, []).append(line)

    blocks: list[str] = ["Built-in tools", ""]
    for tag in _ORDER:
        rows = buckets.pop(tag, None)
        if not rows:
            continue
        blocks.append(f"{tool_family_label(tag)}")
        blocks.extend(sorted(rows))
        blocks.append("")
    for tag in sorted(buckets):
        blocks.append(tool_family_label(tag))
        blocks.extend(sorted(buckets[tag]))
        blocks.append("")
    blocks.append("○ inspect  ✎ edit  $ shell  ↗ network  ◈ crew  ◆ skill")
    return "\n".join(blocks).rstrip() + "\n"
