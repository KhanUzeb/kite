"""Pick bash vs PowerShell vs default shell for a command string."""

from __future__ import annotations

import re
import shutil
import sys

_PS_MARKERS = re.compile(
    r"(?i)(?:\bGet-|\bSet-|\bSelect-Object\b|\bWhere-Object\b|\$env:|\$_|\$PSItem|"
    r"\bInvoke-|\bOut-File\b|\bConvertTo-|\bFormat-Table\b)"
)
_UNIX_MARKERS = re.compile(
    r"(?:&&|\|\||\$\(|`[^`]+`|(?<!\w)(?:grep|sed|awk|find|xargs|wc|head|tail|rg)\b)"
)


def _looks_powershell(command: str) -> bool:
    return bool(_PS_MARKERS.search(command))


def _looks_unix_shell(command: str) -> bool:
    if sys.platform == "win32" and _looks_powershell(command):
        return False
    return bool(_UNIX_MARKERS.search(command))


def resolve_shell_invocation(command: str) -> tuple[list[str] | None, str]:
    """Return (argv, command) for subprocess.

    When argv is not None, run with shell=False and the explicit argv.
    Otherwise use shell=True with the returned command string.
    """
    text = (command or "").strip()
    if not text:
        return None, text
    if sys.platform != "win32":
        return None, text
    if _looks_powershell(text):
        return (
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                text,
            ],
            text,
        )
    bash = shutil.which("bash")
    if bash and _looks_unix_shell(text):
        return ([bash, "-lc", text], text)
    return None, text
