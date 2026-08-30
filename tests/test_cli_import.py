"""CLI import is cheap until a command needs the agent stack."""

from __future__ import annotations

import subprocess
import sys


def test_cli_module_does_not_import_repl_or_harness() -> None:
    code = (
        "import kite.cli.run, sys\n"
        "heavy = ('kite.ui.repl', 'kite.agent.harness', 'kite.agent.runtime', 'kite.tools.coding')\n"
        "bad = [n for n in heavy if n in sys.modules]\n"
        "assert not bad, bad\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout
