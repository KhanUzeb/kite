"""Subprocess helpers for provider CLI delegation.

Two invariants hold for every delegated provider CLI (claude, agy, grok, ...):

1. **A child must not drive the user's terminal.** On Windows a process attached
   to the same console can call ``SetConsoleTitle`` on the whole window even when
   its stdout/stderr are pipes. Claude Code does exactly that: a plain
   ``claude auth status --json`` retitled the user's tab to ``claude`` while kite
   was running, which reads as "some other agent launched". The escape is
   ``CREATE_NO_WINDOW``, which leaves the child unassociated with the parent's
   console. Piping stdout does NOT help here — verified empirically, as does env
   sanitization and stdin redirection: none of them stopped the retitle. See
   ``tests/test_auth_cli_env.py``.

2. **A delegated probe must not inherit the parent agent's interactive-session
   identity.** ``CLAUDE_*`` / ``ANTHROPIC_*`` in the environment describe the
   agent session kite itself is running under, not the identity the child should
   authenticate as, so they are dropped. Notably ``ANTHROPIC_API_KEY`` is kite's
   own LiteLLM routing credential: forwarding it makes ``claude auth status``
   report an API-key login that is not the Claude subscription kite is asking
   about. Everything a child needs to find its binary, reach its keychain/store
   and finish a login is kept — PATH, HOME, USERPROFILE, TEMP/TMP, SystemRoot,
   locale, and every non-Anthropic credential.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable

# Session-identity markers a delegated child must never inherit. Matched as
# case-insensitive prefixes against the environment.
_SESSION_IDENTITY_PREFIXES = ("CLAUDE", "ANTHROPIC")

# Kite's own terminal-UI knobs. These describe the REPL that is *currently*
# drawing the screen; a delegated child is not that REPL and must not size itself
# or read input as if it were. KITE_HOME / KITE_OFFLINE are deliberately NOT
# here — those are config a child may legitimately read.
_KITE_TUI_ENV = frozenset(
    {
        "KITE_BUSY_ENTER",
        "KITE_COMPACT_UI",
        "KITE_FONT",
        "KITE_LOADER",
        "KITE_MOUSE",
        "KITE_NO_MOUSE_PICK",
        "KITE_PICK_DEBUG",
        "KITE_THEME",
        "KITE_TYPED_PICK",
    }
)


def _is_session_identity(name: str) -> bool:
    upper = name.upper()
    return any(upper.startswith(prefix) for prefix in _SESSION_IDENTITY_PREFIXES)


def provider_cli_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a sanitized copy of the environment for a delegated provider CLI.

    Starts from ``base`` (or ``os.environ``) and drops session-identity markers
    (see module docstring). Kept verbatim: PATH, HOME, USERPROFILE, TEMP/TMP,
    SystemRoot, locale vars and all credential vars other than Anthropic's, so
    logins still work.
    """
    source = os.environ if base is None else base
    return {
        name: value
        for name, value in source.items()
        if not _is_session_identity(name) and name.upper() not in _KITE_TUI_ENV
    }


def console_isolation_kwargs() -> dict[str, object]:
    """``run``/``Popen`` kwargs keeping a child's console writes out of ours.

    Windows only: ``CREATE_NO_WINDOW`` gives the child no console of its own and
    leaves it unassociated with the parent's, so it cannot retitle or repaint the
    user's terminal. stdin=PIPE data delivery and stdout/stderr capture are
    unaffected (verified).

    POSIX has no equivalent hazard: there is no per-window console object, so
    retitling is only reachable through the child's own stdout/stderr — already
    pipes here — and the residual risk (a child opening /dev/tty directly) is not
    worth detaching the process group, which would break Ctrl+C for logins.
    """
    if sys.platform != "win32":
        return {}
    # getattr, not attribute access: the constant is defined only under
    # CPython's `if _mswindows:` block, so a direct reference is an
    # AttributeError on any POSIX build.
    flag = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if flag is None:
        return {}
    return {"creationflags": flag}


def run_cli(
    command: str,
    *args: str,
    timeout: float = 60.0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a provider CLI with secrets kept out of exception messages."""
    return subprocess.run(
        [command, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=provider_cli_env(env),
        check=False,
        **console_isolation_kwargs(),
    )


def run_checked(command: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    proc = run_cli(command, *args, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"{command} exited with status {proc.returncode}")
    return proc


def run_cli_streaming(
    command: str,
    *args: str,
    timeout: float = 60.0,
    on_line: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a provider CLI, delivering stdout+stderr lines as they arrive.

    Used by OAuth logins that must surface a sign-in URL before the child
    exits (a fully captured run would hide the URL until it is too late).

    The OAuth logins (grok, agy) are the most visible delegated children, so
    this path needs the same two guards as ``run_cli``: a sanitized env, and
    console isolation so a child cannot retitle the user's terminal.
    """
    proc = subprocess.Popen(
        [command, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=provider_cli_env(env),
        **console_isolation_kwargs(),
    )
    chunks: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:
                    pass

    worker = threading.Thread(target=_reader, daemon=True)
    worker.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        worker.join(timeout=1.0)
        raise
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        worker.join(timeout=1.0)
        raise
    worker.join(timeout=1.0)
    out = "".join(chunks)
    return subprocess.CompletedProcess([command, *args], proc.returncode, out, "")
