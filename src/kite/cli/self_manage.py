"""Self-management: `kite update` / `kite uninstall` for uv-tool installs.

Managed install = `kite` shows up in `uv tool list` (global CLI or editable
dev install). Anything else (plain pip, venv, source checkout on PATH) gets
tailored manual guidance instead of a broken half-upgrade.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

DEFAULT_REPO = "https://github.com/KhanUzeb/kite.git"
DEFAULT_REF = "main"


def _console():
    from kite.ui.style import make_console

    return make_console(stderr=True)


def _uv() -> str | None:
    return shutil.which("uv")


def _uv_tool_names() -> set[str] | None:
    """Names from `uv tool list`, or None when uv is missing/broken."""
    uv = _uv()
    if not uv:
        return None
    try:
        proc = subprocess.run(
            [uv, "tool", "list"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    names: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-"):
            continue
        names.add(stripped.split()[0].lower())
    return names


def _managed() -> bool:
    names = _uv_tool_names()
    return bool(names and "kite" in names)


def _kite_home() -> str:
    return os.environ.get("KITE_HOME") or os.path.join(os.path.expanduser("~"), ".kite")


def _install_kind() -> str:
    """Best-effort label for where this kite process runs from."""
    try:
        import kite

        path = str(getattr(kite, "__file__", "") or "")
    except Exception:
        path = ""
    lowered = path.replace("\\", "/").lower()
    if not path:
        return "unknown"
    if "/site-packages/" in lowered or "\\site-packages\\" in lowered:
        return "uv tool" if _managed() else "site-packages"
    if ".venv" in lowered or "/venv/" in lowered:
        return "virtualenv"
    return "source checkout"


def cmd_update(args: argparse.Namespace) -> int:
    """Upgrade the managed kite CLI in place (uv tool upgrade, git fallback)."""
    from kite import __version__

    console = _console()
    kind = _install_kind()
    if getattr(args, "check", False):
        managed = "uv tool" if _managed() else kind
        console.print(f"[kite.brand]kite[/]  {__version__}  [kite.muted]({managed})[/]")
        return 0
    uv = _uv()
    if not uv:
        console.print("[red]uv not found[/]  [kite.muted]— reinstall with the bootstrap script:[/]")
        console.print("  [kite.muted]Windows:[/] irm https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.ps1 | iex")
        console.print("  [kite.muted]macOS/Linux:[/] curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/download.sh | bash")
        return 1
    if not _managed():
        try:
            import kite

            where = str(getattr(kite, "__file__", "") or "")
        except Exception:
            where = ""
        console.print(f"[kite.brand]kite[/]  {__version__}  [kite.muted]({kind})[/]")
        console.print("[kite.muted]not a `uv tool` install — self-update is unavailable here.[/]")
        if where:
            console.print(f"[kite.muted]running from:[/] {where}")
        console.print("[kite.muted]global CLI:[/] uv tool install --force \"git+https://github.com/KhanUzeb/kite.git\"")
        console.print("[kite.muted]dev checkout:[/] git pull && uv tool install --force --editable .")
        return 2
    ref = (getattr(args, "ref", None) or os.environ.get("KITE_REPO_REF") or DEFAULT_REF).strip() or DEFAULT_REF
    repo = (getattr(args, "repo", None) or os.environ.get("KITE_REPO_URL") or DEFAULT_REPO).strip() or DEFAULT_REPO
    force_reinstall = bool(getattr(args, "force", False)) or bool(getattr(args, "ref", None))

    def _reinstall() -> int:
        # Strip a literal ".git" suffix only (never char-trim — "kite.git" must stay "kite").
        base = repo[:-4] if repo.endswith(".git") else repo
        spec = f"git+{base}.git@{ref}"
        console.print(f"[kite.muted]reinstalling from[/] {spec}")
        try:
            proc = subprocess.run([uv, "tool", "install", "--force", spec], timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            console.print(f"[red]reinstall failed[/]  {e}")
            return 1
        return 0 if proc.returncode == 0 else 1

    rc = 0
    if not force_reinstall:
        console.print(f"[kite.muted]upgrading kite {__version__} → latest {ref}…[/]")
        try:
            proc = subprocess.run([uv, "tool", "upgrade", "kite"], timeout=600)
            rc = proc.returncode
        except (OSError, subprocess.TimeoutExpired) as e:
            console.print(f"[kite.muted]upgrade error ({e}) — trying reinstall…[/]")
            rc = _reinstall()
        if rc != 0:
            console.print("[kite.muted]upgrade failed — trying reinstall from git…[/]")
            rc = _reinstall()
    else:
        rc = _reinstall()
    if rc != 0:
        console.print("[red]update failed[/]  [kite.muted]check network/git, or rerun the install script.[/]")
        return 1
    try:
        shim = shutil.which("kite")
        if shim:
            proc = subprocess.run([shim, "--version"], capture_output=True, text=True, timeout=60)
            out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if out:
                console.print(f"[kite.success]updated[/]  {out.splitlines()[0]}")
                return 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    console.print("[kite.success]updated[/]  [kite.muted]open a new shell if `kite --version` looks stale.[/]")
    return 0


def _purge_home(home: str) -> tuple[bool, int, str]:
    """Remove the ~/.kite data dir, retrying read-only files (Windows/git).

    Returns (removed, leftover_files, error). `removed` is True only when the
    dir is fully gone; otherwise `leftover_files` counts what is still on
    disk so the CLI can report removed vs kept instead of a bare failure.
    """
    import stat

    def _onerror(func, path, _exc_info) -> None:
        try:
            os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
            func(path)
        except OSError:
            pass

    try:
        shutil.rmtree(home, ignore_errors=False, onerror=_onerror)
    except OSError as e:
        leftover = _count_files(home)
        return False, leftover, str(e)
    if os.path.exists(home):
        return False, _count_files(home), f"{home} still exists"
    return True, 0, ""


def _count_files(root: str) -> int:
    total = 0
    try:
        for _dir, _subdirs, files in os.walk(root):
            total += len(files)
    except OSError:
        pass
    return total


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Remove the managed kite CLI. ~/.kite data (sessions, keys) is kept unless --purge."""
    console = _console()
    home = _kite_home()
    purge = bool(getattr(args, "purge", False))
    if not _managed():
        console.print(f"[kite.muted]not a `uv tool` install ({_install_kind()}) — nothing to uninstall.[/]")
        console.print("[kite.muted]pip/venv:[/] pip uninstall kite")
        console.print("[kite.muted]dev checkout:[/] uv tool uninstall kite  (if it was installed --editable)")
        return 2
    yes = bool(getattr(args, "yes", False))
    if not yes:
        if not sys.stdin.isatty():
            # Headless/scripted: the operator typed the command — proceed like
            # `uv tool uninstall` itself (no prompt to hang on).
            console.print("[kite.muted]non-interactive — proceeding without confirmation[/]")
        else:
            what = "kite CLI + " + home + " data" if purge else "kite CLI (keeps " + home + " data)"
            try:
                answer = console.input(f"Uninstall {what}? [y/N]: ")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Cancelled[/]")
                return 130
            if answer.strip().lower() not in {"y", "yes"}:
                console.print("[yellow]Cancelled[/]")
                return 130
    uv = _uv()
    if not uv:  # pragma: no cover - managed implies uv exists
        console.print("[red]uv not found[/]")
        return 1
    try:
        proc = subprocess.run([uv, "tool", "uninstall", "kite"], timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        console.print(f"[red]uninstall failed[/]  {e}")
        return 1
    if proc.returncode != 0:
        console.print("[red]uninstall failed[/]  [kite.muted]try: uv tool uninstall kite[/]")
        return 1
    if purge:
        removed, leftover, error = _purge_home(home)
        if removed:
            console.print(f"[kite.muted]removed data dir[/]  {home}")
        elif leftover:
            console.print(
                f"[yellow]CLI removed, but kept {leftover} leftover file(s) in {home}: {error}[/]"
            )
            console.print("[kite.muted]close shells/editors using it, then:[/]  kite uninstall --purge")
            return 1
        else:
            console.print(f"[yellow]CLI removed, but could not delete {home}: {error}[/]")
            return 1
    else:
        console.print(f"[kite.muted]kept data at[/]  {home}  [kite.muted](sessions, keys)[/]")
        console.print("[kite.muted]remove it later:[/]  kite uninstall --purge")
    console.print("[kite.success]uninstalled[/]  [kite.muted]restart the shell so `kite` leaves PATH.[/]")
    return 0
