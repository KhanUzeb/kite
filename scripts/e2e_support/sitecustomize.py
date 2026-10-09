"""Loaded only by e2e_smoke subprocesses via their private PYTHONPATH."""

import sys


def _loopback_only(event, args):
    if event == "socket.connect":
        address = args[1]
        # AF_UNIX is local too (e.g. interpreter/platform services).
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
            raise RuntimeError(f"smoke test blocked external connection to {address[0]!r}")
    elif event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "::1", "localhost", None}:
        raise RuntimeError(f"smoke test blocked external DNS for {args[0]!r}")


sys.addaudithook(_loopback_only)
