"""Per-user harness dashboard — full coding-agent activity at a glance."""

from __future__ import annotations

import time

from kite.memory.session import resolve_session_path
from kite.memory.session_analytics import (
    build_dashboard_summary,
    list_session_events,
    scan_session_file,
)


def _bar(value: int, total: int, width: int = 24) -> str:
    if total <= 0 or value <= 0:
        return "░" * width
    filled = max(1, int(width * value / total))
    return "█" * filled + "░" * (width - filled)


def _fmt_ts(ts: float) -> str:
    if ts <= 0:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _event_line(kind: str, payload: dict) -> str:
    if kind == "tool_end":
        tool = payload.get("tool") or "?"
        ok = payload.get("ok", True)
        mark = "✓" if ok and not payload.get("blocked") else "⚠"
        return f"{mark} {tool}"
    if kind == "agent_end":
        return f"end → {payload.get('exit_status') or 'done'}"
    if kind == "tool_start":
        return f"→ {payload.get('tool') or '?'}"
    if kind == "compact":
        return f"compact {payload.get('before')}→{payload.get('after')}"
    if kind == "interrupt":
        return "interrupted"
    if kind == "subagent_start":
        return f"subagent {payload.get('label') or payload.get('id') or ''}".strip()
    if kind == "checkpoint":
        return f"checkpoint {payload.get('label') or ''}".strip()
    if kind == "approval":
        return "approval gate"
    return kind


def cmd_dashboard(args) -> int:
    from rich.columns import Columns
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from kite import __version__
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    summary = build_dashboard_summary(limit=int(getattr(args, "limit", 200) or 200))
    user = summary.user

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
            payload = stats.to_dict()
            payload["events"] = list_session_events(path, limit=30)
            console.print_json(data=payload)
            return 0

        title = f"Session {stats.session_id}"
        console.print(Panel(title, border_style="cyan"))
        meta = Table(show_header=False, box=None, padding=(0, 1))
        meta.add_row("user", user.username)
        meta.add_row("task", stats.task[:200] or "—")
        meta.add_row("label", stats.label[:80] or "—")
        meta.add_row("cwd", stats.cwd or "—")
        meta.add_row("model", f"{stats.provider}/{stats.model}" or "—")
        meta.add_row("mode", stats.mode or "—")
        meta.add_row("approval", stats.approval or "—")
        meta.add_row("started", _fmt_ts(stats.created_at))
        meta.add_row("updated", _fmt_ts(stats.updated_at))
        meta.add_row("duration", f"{stats.duration_s:.0f}s")
        meta.add_row("status", stats.exit_status or "in progress")
        meta.add_row("verification", stats.verification_status or "—")
        if stats.last_error:
            meta.add_row("error", stats.last_error[:120])
        console.print(Panel(meta, title="Run", border_style="blue"))

        activity = Table(show_header=False, box=None, padding=(0, 1))
        activity.add_row("turns", str(stats.turn_count))
        activity.add_row("messages", str(stats.message_count))
        activity.add_row("api calls", str(stats.api_calls))
        activity.add_row("tool calls", str(stats.tool_calls))
        activity.add_row("failures", str(stats.tool_failures))
        activity.add_row("blocked", str(stats.tool_blocked))
        activity.add_row("writes/edits", str(stats.write_edits))
        activity.add_row("bash", str(stats.bash_calls))
        activity.add_row("subagents", str(stats.subagent_runs))
        activity.add_row("compactions", str(stats.compaction_count))
        activity.add_row("checkpoints", str(stats.checkpoints))
        activity.add_row("approvals", str(stats.approvals))
        activity.add_row("interrupts", str(stats.interrupts))
        activity.add_row("cost", f"${stats.cost:.4f}")
        activity.add_row("tokens (est.)", str(stats.estimated_tokens or "—"))
        activity.add_row("cache hits", str(stats.cache_hit_tokens or "—"))
        console.print(Panel(activity, title="Activity", border_style="green"))

        if stats.tool_counts:
            tools = Table(title="Tools")
            tools.add_column("tool")
            tools.add_column("count", justify="right")
            for name, count in sorted(stats.tool_counts.items(), key=lambda x: -x[1]):
                tools.add_row(name, str(count))
            console.print(tools)

        events = list_session_events(path, limit=15)
        if events:
            timeline = Table(title="Recent events", show_header=True)
            timeline.add_column("time", style="dim")
            timeline.add_column("event")
            for ev in events:
                timeline.add_row(_fmt_ts(ev["ts"])[-11:], _event_line(ev["kind"], ev["payload"]))
            console.print(timeline)

        console.print(
            f"[dim]Resume:[/] [cyan]kite resume {stats.session_id}[/]  "
            f"[dim]· file:[/] {path}"
        )
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
            (user.username, "bold green"),
            ("  ·  ", "dim"),
            (f"{summary.session_count} sessions", "cyan"),
        )
        console.print(Panel(header, border_style="cyan"))

        profile = Table.grid(padding=(0, 2))
        profile.add_column(justify="right", style="bold")
        profile.add_column()
        profile.add_row("Kite home", user.kite_home)
        profile.add_row("Default model", f"{user.default_provider}/{user.default_model}")
        profile.add_row("Limits", f"{user.step_limit} steps · ${user.cost_limit:.2f} budget")
        profile.add_row("Sessions path", user.sessions_dir)
        console.print(Panel(profile, title=f"Your workspace ({user.username})", border_style="green"))

        health = Table.grid(padding=(0, 2))
        health.add_column(justify="right", style="bold")
        health.add_column()
        health.add_row("Active now", str(summary.active_sessions))
        health.add_row("Completed", str(summary.completed_sessions))
        health.add_row("Failed / stalled", str(summary.failed_sessions_count))
        health.add_row("Last 24h", f"{summary.sessions_last_24h} sessions · ${summary.cost_last_24h:.3f}")
        health.add_row("Avg duration", f"{summary.avg_duration_s:.0f}s")
        console.print(Panel(health, title="Agent health", border_style="blue"))

        overview = Table.grid(padding=(0, 2))
        overview.add_column(justify="right", style="bold")
        overview.add_column()
        overview.add_row("Tool calls", f"{summary.total_tool_calls:,}")
        overview.add_row("API calls", f"{summary.total_api_calls:,}")
        overview.add_row("Write/edit ops", f"{summary.total_write_edits:,}")
        overview.add_row("Subagents", f"{summary.total_subagents:,}")
        overview.add_row("Est. tokens", f"{summary.total_estimated_tokens:,}")
        overview.add_row("Cache hits", f"{summary.total_cache_hits:,}")
        overview.add_row("Total cost", f"${summary.total_cost:.3f}")
        console.print(Panel(overview, title="Totals", border_style="magenta"))

        if summary.status_counts:
            status_tbl = Table(title="Exit status")
            status_tbl.add_column("status")
            status_tbl.add_column("count", justify="right")
            for name, count in sorted(summary.status_counts.items(), key=lambda x: -x[1])[:10]:
                status_tbl.add_row(name, str(count))
            console.print(status_tbl)

        cols: list[Table] = []
        if summary.provider_totals:
            prov = Table(title="Providers")
            prov.add_column("provider")
            prov.add_column("sessions", justify="right")
            for name, count in sorted(summary.provider_totals.items(), key=lambda x: -x[1])[:6]:
                prov.add_row(name, str(count))
            cols.append(prov)
        if summary.model_totals:
            models = Table(title="Models")
            models.add_column("provider/model")
            models.add_column("sessions", justify="right")
            for name, count in sorted(summary.model_totals.items(), key=lambda x: -x[1])[:6]:
                models.add_row(name[:36], str(count))
            cols.append(models)
        if cols:
            console.print(Columns(cols, equal=True, expand=True))

        if summary.tool_totals:
            top_tools = sorted(summary.tool_totals.items(), key=lambda x: -x[1])[:8]
            total_tools = sum(summary.tool_totals.values())
            tool_panel = Table(title="Tool usage")
            tool_panel.add_column("tool")
            tool_panel.add_column("share", width=28)
            tool_panel.add_column("count", justify="right")
            for name, count in top_tools:
                tool_panel.add_row(name, _bar(count, total_tools), str(count))
            console.print(tool_panel)

        if summary.attention_sessions:
            attn = Table(title="Needs attention (failed, active, tool errors)")
            attn.add_column("id", style="cyan")
            attn.add_column("status")
            attn.add_column("tools", justify="right")
            attn.add_column("fail", justify="right")
            attn.add_column("task")
            for s in summary.attention_sessions[:6]:
                attn.add_row(
                    s.session_id[:20],
                    s.exit_status or "active",
                    str(s.tool_calls),
                    str(s.tool_failures),
                    (s.label or s.task)[:36],
                )
            console.print(attn)

        recent = Table(title="Recent sessions")
        recent.add_column("id", style="cyan")
        recent.add_column("updated")
        recent.add_column("status")
        recent.add_column("cost", justify="right")
        recent.add_column("tools", justify="right")
        recent.add_column("label")
        for s in summary.recent_sessions[:8]:
            recent.add_row(
                s.session_id[:20],
                _fmt_ts(s.updated_at)[-11:],
                s.exit_status or "…",
                f"${s.cost:.3f}",
                str(s.tool_calls),
                (s.label or s.task)[:32],
            )
        console.print(recent)

        costly = Table(title="Highest cost")
        costly.add_column("id", style="cyan")
        costly.add_column("cost", justify="right")
        costly.add_column("tokens", justify="right")
        costly.add_column("duration", justify="right")
        costly.add_column("status")
        for s in summary.highest_cost_sessions[:5]:
            costly.add_row(
                s.session_id[:20],
                f"${s.cost:.3f}",
                str(s.estimated_tokens or "—"),
                f"{s.duration_s:.0f}s",
                s.exit_status or "…",
            )
        console.print(costly)

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
                    user = summary.user
                    _render()
                    time.sleep(watch)
        except KeyboardInterrupt:
            pass
        return 0

    _render()
    return 0
