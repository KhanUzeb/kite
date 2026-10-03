"""Model turns through the signed-in `agy` CLI — no API key required.

The agy session lives in the OS keyring (no file tokens to materialize like
Codex/Grok), so subscription turns are delegated to the binary itself::

    echo <prompt> | agy --model <id> --mode plan --output-format json

The prompt travels on stdin, never argv: Windows caps the command line at
~32K chars (WinError 206) and Kite turns carry a full system prompt plus
history. ``--mode plan`` keeps agy read-only: Kite owns tools/edits, agy
only answers. Replies are text-only (agy cannot return Kite tool calls),
so casual chat works on subscription while tool-driven agent runs still
need GEMINI_API_KEY.

`agy -p --output-format json` prints one JSON object::

    {"status": "OK"|"ERROR", "response": "...", "error": "...",
     "usage": {"input_tokens": 0, "output_tokens": 0, ...}}
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass

from kite.guardrails.env_filter import filtered_child_env

_AGY_BIN = "agy"
# Bound the flattened prompt: agy context is finite and smaller turns are
# cheaper/faster. stdin has no OS length cap (unlike argv — WinError 206).
_MAX_PROMPT_CHARS = 24_000


class AntigravityExecError(RuntimeError):
    """`agy -p` failed (not linked, unknown model, bad output, ...)."""


class AntigravityQuotaError(RuntimeError):
    """Subscription quota exhausted — retrying cannot help (reset clock)."""


@dataclass(frozen=True)
class AgyTurn:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


def agy_executable() -> str | None:
    return shutil.which(_AGY_BIN)


def _text_part(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content") or ""
                if isinstance(text, str) and text:
                    bits.append(text)
        return "\n".join(bits)
    return ""


def flatten_prompt(messages: list[dict]) -> str:
    """Collapse system + turns into the single prompt `agy -p` accepts.

    Tool traffic is inlined as plain text (agy never sees Kite tool calls).
    Oldest non-system history is dropped first, then a hard
    ``_MAX_PROMPT_CHARS`` bound is enforced: the system block plus the
    newest turn (the current request) are preserved and the middle is
    dropped; if even that exceeds the bound, the oldest content is
    truncated with a ``[truncated ...]`` marker. Output never exceeds
    ``_MAX_PROMPT_CHARS`` chars.
    """
    system_bits: list[str] = []
    turns: list[str] = []
    for msg in messages:
        role = str(msg.get("role") or "")
        if role == "tool":
            continue
        text = _text_part(msg.get("content")).strip()
        if not text:
            continue
        if role == "system":
            system_bits.append(text)
            continue
        if role == "assistant":
            calls = msg.get("tool_calls") or []
            if isinstance(calls, list) and calls:
                names = ", ".join(
                    str((c.get("function") or {}).get("name") or c.get("name") or "?")
                    for c in calls
                    if isinstance(c, dict)
                )
                text += f"\n[tool calls requested (not executed in subscription mode): {names}]"
            turns.append(f"Assistant: {text}")
        else:
            turns.append(f"User: {text}")
    head = "\n\n".join(system_bits).strip()
    # Trim oldest turns first; always keep the tail.
    while turns and len(head) + sum(len(t) + 2 for t in turns) > _MAX_PROMPT_CHARS:
        if len(turns) <= 2:
            break
        turns.pop(0)
    body = "\n\n".join(turns)
    if head and body:
        prompt = f"<system>\n{head}\n</system>\n\n{body}"
    else:
        prompt = head or body
    if len(prompt) <= _MAX_PROMPT_CHARS:
        return prompt
    # Hard bound: preserve the system block + newest turn (current request),
    # drop the middle first.
    middle_marker = "...[earlier history truncated to fit prompt limit]..."
    tail_marker = "\n...[truncated to fit prompt limit]"
    last = turns[-1] if turns else ""
    sys_block = f"<system>\n{head}\n</system>\n\n" if head else ""
    if last and len(sys_block) + len(last) + len(middle_marker) + 2 <= _MAX_PROMPT_CHARS:
        return f"{sys_block}{middle_marker}\n\n{last}"
    if last and sys_block and len(last) + len(tail_marker) + 2 < _MAX_PROMPT_CHARS:
        budget_sys = _MAX_PROMPT_CHARS - len(last) - len(tail_marker) - 2
        return f"{sys_block[:budget_sys]}{tail_marker}\n\n{last}"
    # Even the newest turn alone (or a system-only prompt) exceeds the bound:
    # head-truncate with a marker so output never exceeds _MAX_PROMPT_CHARS.
    text = (sys_block + last) if last else prompt
    budget = _MAX_PROMPT_CHARS - len(tail_marker)
    return f"{text[:budget]}{tail_marker}" if len(text) > budget else text


def build_agy_argv(*, model: str, with_model: bool = True) -> list[str]:
    """Short argv only — the prompt itself travels on stdin (no length cap)."""
    exe = agy_executable() or _AGY_BIN
    argv = [exe]
    if with_model and (model or "").strip():
        argv += ["--model", model.strip()]
    return argv + ["--mode", "plan", "--output-format", "json"]


def _extract_json(text: str) -> dict:
    """Parse agy's JSON object out of stdout (warnings may surround it)."""
    raw = (text or "").strip()
    if not raw:
        raise AntigravityExecError("agy printed no output (not linked? run: kite login antigravity)")
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise AntigravityExecError(f"agy printed non-JSON output: {raw[:200]}")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        raise AntigravityExecError(f"agy printed malformed JSON: {raw[:200]}") from None
    if not isinstance(payload, dict):
        raise AntigravityExecError(f"agy printed unexpected JSON: {raw[:200]}")
    return payload


def _is_quota_error(text: str) -> bool:
    lowered = (text or "").lower()
    return "quota" in lowered and ("resets in" in lowered or "upgrade your subscription" in lowered)


def _is_unknown_model_error(text: str) -> bool:
    lowered = (text or "").lower()
    return "unknown model" in lowered or "model not found" in lowered or "invalid model" in lowered


def parse_agy_payload(payload: dict) -> AgyTurn:
    err = str(payload.get("error") or "").strip()
    response = str(payload.get("response") or "").strip()
    if err and not response:
        if _is_quota_error(err):
            raise AntigravityQuotaError(f"Antigravity subscription quota reached. {err}")
        raise AntigravityExecError(f"agy turn failed: {err[:300]}")
    if not response:
        raise AntigravityExecError("agy returned an empty response")
    usage = payload.get("usage") or {}
    try:
        in_tokens = int(usage.get("input_tokens") or 0)
    except (TypeError, ValueError):
        in_tokens = 0
    try:
        out_tokens = int(usage.get("output_tokens") or 0)
    except (TypeError, ValueError):
        out_tokens = 0
    return AgyTurn(text=response, input_tokens=in_tokens, output_tokens=out_tokens)


def run_agy_turn(
    *,
    model: str,
    messages: list[dict],
    timeout_seconds: float = 300.0,
    should_stop: Callable[[], bool] | None = None,
    cwd: str | None = None,
) -> AgyTurn:
    """Execute one subscription turn via the agy CLI; return text + usage."""
    if agy_executable() is None:
        raise AntigravityExecError(
            "agy CLI not found. Install it from "
            "https://antigravity.google/docs/cli/install/ "
            "or set GEMINI_API_KEY for direct API access."
        )
    prompt = flatten_prompt(messages)
    if not prompt.strip():
        raise AntigravityExecError("empty prompt — nothing to send to agy")
    timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else 600.0
    attempts = [True, False]  # with --model, then without (stale default model)
    last_error: Exception | None = None
    for with_model in attempts:
        if should_stop is not None and should_stop():
            raise InterruptedError("interrupted")
        try:
            out = _run_agy_process(
                build_agy_argv(model=model, with_model=with_model),
                input_text=prompt,
                timeout=timeout,
                should_stop=should_stop,
                cwd=cwd,
            )
        except AntigravityExecError as exc:
            last_error = exc
            if with_model and _is_unknown_model_error(str(exc)):
                continue
            raise
        try:
            return parse_agy_payload(_extract_json(out))
        except AntigravityExecError as exc:
            last_error = exc
            if with_model and _is_unknown_model_error(str(exc)):
                continue
            raise
    assert last_error is not None
    raise last_error


def _run_agy_process(
    argv: list[str],
    *,
    input_text: str,
    timeout: float,
    should_stop: Callable[[], bool] | None,
    cwd: str | None,
) -> str:
    """Run agy with the prompt on stdin (argv stays short — no WinError 206)."""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            # Strip credential-like keys; agy authenticates via the OS
            # keyring, and non-sensitive AGY_* vars pass through untouched.
            env=filtered_child_env(),
        )
    except OSError as exc:
        raise AntigravityExecError(f"could not start agy: {exc}") from None
    box: dict[str, object] = {}

    def _pump() -> None:
        try:
            out, _ = proc.communicate(input=input_text)
            box["out"] = out
        except Exception as exc:  # noqa: BLE001 — surfaced below
            box["error"] = exc
        finally:
            box["done"] = True

    worker = threading.Thread(target=_pump, daemon=True, name="kite-agy-pump")
    worker.start()
    import time as _time

    deadline = _time.monotonic() + timeout
    while not box.get("done"):
        if should_stop is not None and should_stop():
            try:
                proc.kill()
            except OSError:
                pass
            worker.join(timeout=2.0)
            raise InterruptedError("interrupted")
        if _time.monotonic() >= deadline:
            try:
                proc.kill()
            except OSError:
                pass
            worker.join(timeout=2.0)
            raise TimeoutError(f"agy request timed out after {int(timeout)}s")
        _time.sleep(0.2)
    worker.join(timeout=2.0)
    try:
        proc.wait(timeout=5.0)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if box.get("error") is not None:
        raise AntigravityExecError(f"agy I/O failed: {box['error']}")
    out = str(box.get("out") or "")
    if proc.returncode not in (0, None) and not out.strip():
        raise AntigravityExecError(f"agy exited with status {proc.returncode} and no output")
    return out
