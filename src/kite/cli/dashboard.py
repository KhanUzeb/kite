"""User-facing harness dashboard — sessions, tokens, tools, cache."""

from __future__ import annotations

import time

from kite.memory.session_analytics import (
    build_dashboard_summary,
    load_session_stats,
    scan_session_file,
)
from kite.memory.session import resolve_session_path, sessions_dir


def _bar(value: int, total: int, width: int = 24) -> str:
    if total <= 0 or value <= 0:
        return "░" * width
    filled = max(1, int(width * value / total))
    return "█" * filled + "░" * (width - filled)


def cmd_dashboard(args) -> int:
    from rich.columns import Columns
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from kite import __version__
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    summary = build_dashboard_summary(limit=int(getattr(args, "limit", 200) or 200))

    if getattr(args, "session", None):
        sid = str(args.session)
        try:
            path = resolve_session_path(sid)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]{e}[/]")
            return 1
        stats = scan_session_file(path)
        if stats is None:
            console.print(f"[red]Could not read session {sid}[/]")
            return 1
        if getattr(args, "json", False):
            console.print_json(data=stats.to_dict())
            return 0
        console.print(Panel(f"[bold]Session[/] {stats.session_id}", border_style="cyan"))
        meta = Table(show_header=False, box=None, padding=(0, 1))
        meta.add_row("task", stats.task[:120] or "—")
        meta.add_row("model", f"{stats.provider}/{stats.model}")
        meta.add_row("duration", f"{stats.duration_s:.0f}s")
        meta.add_row("turns", str(stats.turn_count))
        meta.add_row("tools", str(stats.tool_calls))
        meta.add_row("api calls", str(stats.api_calls))
        meta.add_row("cost", f"${stats.cost:.3f}")
        meta.add_row("tokens (est.)", str(stats.estimated_tokens or "—"))
        meta.add_row("cache hits", str(stats.cache_hit_tokens or "—"))
        meta.add_row("compactions", str(stats.compaction_count))
        meta.add_row("status", stats.exit_status or "in progress")
        console.print(meta)
        if stats.tool_counts:
            tools = Table(title="Tool breakdown")
            tools.add_column("tool")
            tools.add_column("count", justify="right")
            for name, count in sorted(stats.tool_counts.items(), key=lambda x: -x[1]):
                tools.add_row(name, str(count))
            console.print(tools)
        return 0

    if getattr(args, "json", False):
        console.print_json(data=summary.to_dict())
        return 0

    watch = int(getattr(args, "watch", 0) or 0)

    def _render() -> None:
        console.clear()
        header = Text.assemble(
            ("Kite ", "bold cyan"),
            (f"v{__version__}  ", "dim"),
            ("dashboard", "bold"),
            ("  ·  ", "dim"),
            (f"{summary.session_count} sessions", "green"),
        )
        console.print(Panel(header, border_style="cyan"))

        overview = Table.grid(padding=(0, 2))
        overview.add_column(justify="right", style="bold")
        overview.add_column()
        overview.add_row("Tool calls", f"{summary.total_tool_calls:,}")
        overview.add_row("API calls", f"{summary.total_api_calls:,}")
        overview.add_row("Est. tokens", f"{summary.total_estimated_tokens:,}")
        overview.add_row("Cache hits", f"{summary.total_cache_hits:,}")
        overview.add_row("Total cost", f"${summary.total_cost:.3f}")
        console.print(Panel(overview, title="Overview", border_style="blue"))

        longest = Table(title="Longest sessions", show_lines=False)
        longest.add_column("id", style="cyan", no_wrap=True)
        longest.add_column("duration", justify="right")
        longest.add_column("tools", justify="right")
        longest.add_column("tokens", justify="right")
        longest.add_column("status")
        for s in summary.longest_sessions[:6]:
            longest.add_row(
                s.session_id[:22],
                f"{s.duration_s:.0f}s",
                str(s.tool_calls),
                str(s.estimated_tokens or "—"),
                s.exit_status or "…",
            )
        console.print(longest)

        if summary.tool_totals:
            top_tools = sorted(summary.tool_totals.items(), key=lambda x: -x[1])[:8]
            total_tools = sum(summary.tool_totals.values())
            tool_panel = Table(title="Tool usage", show_header=True)
            tool_panel.add_column("tool")
            tool_panel.add_column("share", width=28)
            tool_panel.add_column("count", justify="right")
            for name, count in top_tools:
                tool_panel.add_row(name, _bar(count, total_tools), str(count))
            console.print(tool_panel)

        recent = Table(title="Recent sessions")
        recent.add_column("id", style="cyan")
        recent.add_column("updated")
        recent.add_column("tools", justify="right")
        recent.add_column("label")
        for s in summary.recent_sessions[:6]:
            ago = time.strftime("%m-%d %H:%M", time.localtime(s.updated_at))
            recent.add_row(s.session_id[:22], ago, str(s.tool_calls), (s.label or s.task)[:40])
        console.print(recent)

        console.print(
            "[dim]Drill down:[/] [cyan]kite dashboard --session <id>[/]  "
            "[dim]·[/] [cyan]kite dashboard --json[/]  "
            "[dim]·[/] [cyan]kite dashboard --watch 5[/]"
        )

    if watch > 0:
        from rich.live import Live

        try:
            with Live(console=console, refresh_per_second=1, screen=True):
                while True:
                    summary = build_dashboard_summary(limit=int(getattr(args, "limit", 200) or 200))
                    _render()
                    time.sleep(watch)
        except KeyboardInterrupt:
            pass
        return 0

    _render()
    return 0
