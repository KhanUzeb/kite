"""Maintainer dashboard — GitHub reach + local harness activity (private)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from kite.config import kite_home
from kite.memory.audit import AuditLog


def maintainer_enabled() -> bool:
    """True when ~/.kite/.env sets KITE_MAINTAINER_KEY (any non-empty value you choose)."""
    return bool(os.getenv("KITE_MAINTAINER_KEY", "").strip())

_GITHUB_REPO = "KhanUzeb/kite"
_PYPI_PACKAGE = "kite-agent"  # fallback name if published later


def _http_json(url: str, *, timeout: float = 12.0) -> dict | list | None:
    from kite import __version__

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"kite-stats/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def github_stats() -> dict[str, int | str]:
    data = _http_json(f"https://api.github.com/repos/{_GITHUB_REPO}")
    if not isinstance(data, dict):
        return {"error": "GitHub unreachable"}
    return {
        "repo": _GITHUB_REPO,
        "stars": int(data.get("stargazers_count") or 0),
        "forks": int(data.get("forks_count") or 0),
        "watchers": int(data.get("subscribers_count") or 0),
        "open_issues": int(data.get("open_issues_count") or 0),
    }


def pypi_downloads() -> dict[str, int | str]:
    overall = _http_json(f"https://pypistats.org/api/packages/{_PYPI_PACKAGE}/overall")
    if isinstance(overall, dict):
        data = overall.get("data") or []
        last_month = next((row for row in data if row.get("category") == "without_mirrors"), None)
        if isinstance(last_month, dict):
            return {
                "package": _PYPI_PACKAGE,
                "last_month": int(last_month.get("downloads") or 0),
                "source": "pypistats",
            }
    # Package may not exist on PyPI yet — that's fine for a git-install project.
    meta = _http_json(f"https://pypi.org/pypi/{_PYPI_PACKAGE}/json")
    if isinstance(meta, dict):
        info = meta.get("info") or {}
        return {
            "package": _PYPI_PACKAGE,
            "version": str(info.get("version") or ""),
            "source": "pypi",
        }
    return {"package": _PYPI_PACKAGE, "note": "not on PyPI — installs are via git clone / install script"}


def local_usage() -> dict[str, int | float]:
    home = kite_home()
    sessions_dir = home / "sessions"
    session_files = list(sessions_dir.glob("*.jsonl")) if sessions_dir.is_dir() else []
    audit_rows = AuditLog().tail(10_000)
    run_events = sum(1 for row in audit_rows if row.get("kind") == "run")
    trajectories = list((home / "trajectories").glob("*.json")) if (home / "trajectories").is_dir() else []
    return {
        "sessions": len(session_files),
        "trajectories": len(trajectories),
        "audit_events": len(audit_rows),
        "runs_logged": run_events,
    }


def cmd_maintainer_dashboard(args) -> int:
    from rich.panel import Panel
    from rich.table import Table

    from kite import __version__
    from kite.ui.style import make_console

    console = make_console(stderr=True)
    if not maintainer_enabled():
        console.print("[red]Maintainer access required.[/]")
        console.print(f"[dim]Set KITE_MAINTAINER_KEY in {kite_home() / '.env'} (any secret you pick).[/]")
        return 2

    gh = github_stats()
    pypi = pypi_downloads()
    local = local_usage()

    if getattr(args, "json", False):
        console.print_json(
            data={
                "kite_version": __version__,
                "github": gh,
                "pypi": pypi,
                "local": local,
            }
        )
        return 0

    console.print(
        Panel(
            f"[bold]Kite[/] v{__version__}  ·  [dim]{_GITHUB_REPO}[/]\n"
            "Reach (public) + your local harness activity.",
            title="maintainer dashboard",
            border_style="cyan",
        )
    )

    reach = Table(title="Reach")
    reach.add_column("metric")
    reach.add_column("value", justify="right")
    if "error" not in gh:
        reach.add_row("GitHub stars", str(gh.get("stars", "—")))
        reach.add_row("GitHub forks", str(gh.get("forks", "—")))
        reach.add_row("GitHub watchers", str(gh.get("watchers", "—")))
        reach.add_row("Open issues", str(gh.get("open_issues", "—")))
    else:
        reach.add_row("GitHub", str(gh.get("error")))
    if pypi.get("last_month") is not None:
        reach.add_row(f"PyPI downloads ({pypi.get('package')})", str(pypi["last_month"]))
    elif pypi.get("version"):
        reach.add_row(f"PyPI latest ({pypi.get('package')})", str(pypi["version"]))
    else:
        reach.add_row("PyPI", str(pypi.get("note", "—")))
    console.print(reach)

    mine = Table(title="This machine (~/.kite)")
    mine.add_column("metric")
    mine.add_column("value", justify="right")
    mine.add_row("Saved sessions", str(local["sessions"]))
    mine.add_row("Trajectories", str(local["trajectories"]))
    mine.add_row("Audit events", str(local["audit_events"]))
    mine.add_row("Runs in audit log", str(local["runs_logged"]))
    console.print(mine)

    console.print("[dim]Run[/] [cyan]kite maintainer dashboard --json[/] [dim]for scripts.[/]")
    return 0
