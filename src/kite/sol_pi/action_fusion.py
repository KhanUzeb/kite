"""Action Fusion — optional then_run on edit/write (NVlabs/SoL-Pi)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

THEN_RUN_SUCCEEDED = "[then_run:succeeded]"
THEN_RUN_FAILED = "[then_run:failed]"
THEN_RUN_SKIPPED = "[then_run:skipped]"

THEN_RUN_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Bash command to run after a successful mutation"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (optional)"},
    },
    "required": ["command"],
}

_file_queues: dict[str, object] = {}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_unchanged_before_command(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"{THEN_RUN_SKIPPED} target missing; the command was not run.")
    before = file_sha256(path)
    after = file_sha256(path)
    if before != after:
        raise ValueError("target content changed after the fused mutation")


def merge_then_run_output(mutation: dict[str, Any], bash_out: dict[str, Any]) -> dict[str, Any]:
    if not mutation.get("ok"):
        return mutation
    bash_text = str(bash_out.get("output") or bash_out.get("error") or "").strip()
    base = str(mutation.get("output") or "")
    suffix = f"{THEN_RUN_SUCCEEDED}\n{bash_text}" if bash_text else THEN_RUN_SUCCEEDED
    merged = {**mutation, "output": f"{base}\n{suffix}".strip(), "then_run": True}
    if not bash_out.get("ok", True):
        merged["then_run_exit"] = bash_out.get("returncode")
    return merged


def run_mutation_then_run(
    path: Path,
    then_run: dict[str, Any] | None,
    mutate: Callable[[], dict[str, Any]],
    run_bash: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    try:
        mutation = mutate()
    except Exception as exc:
        if then_run is not None:
            raise RuntimeError(f"{THEN_RUN_SKIPPED} {exc}; the command was not run.") from exc
        raise

    if then_run is None:
        return mutation
    if not mutation.get("ok"):
        return mutation

    assert_unchanged_before_command(path)
    bash_args = {"command": str(then_run.get("command") or "")}
    if then_run.get("timeout") is not None:
        bash_args["timeout"] = then_run["timeout"]
    try:
        bash_out = run_bash(bash_args)
        return merge_then_run_output(mutation, bash_out)
    except Exception as exc:
        base = str(mutation.get("output") or "")
        raise RuntimeError(f"{base}\n\n{THEN_RUN_FAILED}\n{exc}") from exc
