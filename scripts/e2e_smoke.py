#!/usr/bin/env python3
# kite-release-version: 1.0.7
"""Real CLI QA against a loopback-only recorded OpenAI server; no provider credentials."""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSI = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[=>])")


class RecordedProvider(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, *_args) -> None:
        return

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"object": "list", "data": [{"id": "gpt-4o-mini", "object": "model"}]}).encode())

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(body)
        turns = sum(m.get("role") == "assistant" for m in body["messages"])
        actions = [
            ("write", {"path": "smoke.py", "content": "value = 'after'\n"}),
            ("bash", {"command": "python -m py_compile smoke.py"}),
            ("submit", {"message": "## Done\nUpdated smoke.py.\n\n## Changed\n- smoke.py\n\n## Verification\n- \u2713 python -m py_compile smoke.py passed."}),
        ]
        if turns >= len(actions):
            self.send_error(409, "recording exhausted: expected successful submit after three turns")
            return
        name, arguments = actions[turns]
        call = {"index": 0, "id": f"smoke-{turns}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}
        base = {"id": f"chatcmpl-smoke-{turns}", "created": 1, "model": "gpt-4o-mini"}
        self.send_response(200)
        if body.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in (({"role": "assistant", "tool_calls": [call]}, None), ({}, "tool_calls")):
                chunk = {**base, "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            call.pop("index")
            self.wfile.write(json.dumps({**base, "object": "chat.completion", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": [call]},
                "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode())


def capture_repl(command: list[str], env: dict[str, str], cwd: Path, width: int, output: Path) -> float:
    import fcntl
    import pty
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, width, 0, 0))
    started = time.perf_counter()
    proc = subprocess.Popen(command, cwd=cwd, env={**env, "COLUMNS": str(width), "LINES": "32"},
                            stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    captured = bytearray()
    sent_help = sent_quit = False
    text = ""
    prompt = "› " if env.get("TERM") == "dumb" else "Ctrl+D quit"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                captured.extend(chunk)
                text = ANSI.sub("", captured.decode(errors="replace"))
                # Answer prompt_toolkit's cursor-position query; do not wait for its timeout.
                if b"\x1b[6n" in chunk:
                    os.write(master, b"\x1b[1;1R")
            # Dumb prompt_toolkit prints its prompt before switching to raw input.
            # Sending CR while ICANON is set converts it to Ctrl+J (insert newline).
            if not termios.tcgetattr(master)[3] & termios.ICANON:
                if not sent_help and prompt in text:
                    os.write(master, b"/help\r")
                    sent_help = True
                help_end = text.rfind("More: /help all")
                if sent_help and not sent_quit and help_end >= 0 and prompt in text[help_end:]:
                    os.write(master, b"/quit\r")
                    sent_quit = True
            if proc.poll() is not None and not ready:
                break
        if proc.poll() is None:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"REPL at {width} columns timed out; see {output}") from exc
        if proc.returncode != 0 or not sent_quit or "Traceback (most recent call last)" in text:
            raise RuntimeError(f"REPL at {width} columns failed: exit={proc.returncode}, slash_completed={sent_quit}")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        os.close(master)
        output.with_suffix(".ansi").write_bytes(captured)
        output.with_suffix(".txt").write_text(ANSI.sub("", captured.decode(errors="replace")).replace("\r", ""), encoding="utf-8")
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Persist stdout, event log, trajectory, sessions and terminal transcripts")
    parser.add_argument("--headless-only", action="store_true", help="Skip POSIX PTY checks (Windows)")
    args = parser.parse_args()
    if os.name != "posix" and not args.headless_only:
        parser.error("PTY checks need POSIX; use --headless-only on Windows")
    output = (args.output or Path(tempfile.mkdtemp(prefix="kite-e2e-artifacts-"))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(f"Artifacts: {output}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordedProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="kite-e2e-") as temporary:
            root = Path(temporary)
            home, workspace = root / "home", root / "workspace-λ-界"
            home.mkdir()
            workspace.mkdir()
            (workspace / "smoke.py").write_text("value = 'before'\n", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("Use python -m py_compile smoke.py to verify edits.\n", encoding="utf-8")
            (home / "config.toml").write_text(
                'default_provider = "openai-compatible"\ndefault_model = "gpt-4o-mini"\n'
                f'[api_bases]\nopenai-compatible = "http://127.0.0.1:{server.server_port}/v1"\n', encoding="utf-8")
            env = {**os.environ, "KITE_HOME": str(home), "KITE_SKIP_SETUP": "1", "KITE_TYPED_PICK": "1",
                   "OPENAI_API_KEY": "smoke-not-a-real-key", "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                   "DO_NOT_TRACK": "1", "KITE_OFFLINE": "1", "TERM": "xterm-256color", "NO_PROXY": "127.0.0.1,localhost",
                   "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                   "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
                   "PYTHONPATH": os.pathsep.join((str(ROOT / "scripts" / "e2e_support"), str(ROOT / "src")))}
            command = [sys.executable, "-m", "kite.cli.run"]
            common = ["--provider", "openai-compatible", "--model", "gpt-4o-mini", "--cwd", str(workspace)]
            before = time.perf_counter()
            result = subprocess.run([*command, "run", "--headless", "--json", "--approval", "auto", "--steps", "4",
                "--output", str(output / "trajectory.json"), *common, "Change smoke.py to value = 'after', verify syntax, and submit."],
                cwd=workspace, env=env, encoding="utf-8", capture_output=True, timeout=60)
            (output / "headless.stdout").write_text(result.stdout, encoding="utf-8")
            (output / "headless.stderr").write_text(result.stderr, encoding="utf-8")
            if (home / "sessions").is_dir():
                shutil.copytree(home / "sessions", output / "sessions", dirs_exist_ok=True)
            if result.returncode != 0 or (workspace / "smoke.py").read_text() != "value = 'after'\n":
                raise RuntimeError(f"headless edit/submit failed (exit {result.returncode}); see {output / 'headless.stderr'}")
            payload = json.loads(result.stdout)
            if payload.get("exit_status") != "Submitted":
                raise RuntimeError(f"headless did not submit: {payload}")
            print(f"PASS headless edit + syntax check + submit: {time.perf_counter() - before:.3f}s", flush=True)
            if not args.headless_only:
                for term in ("xterm-256color", "dumb"):
                    for width in (50, 80, 120):
                        elapsed = capture_repl([*command, "chat", *common], {**env, "TERM": term}, workspace,
                                               width, output / f"repl-{term}-{width}")
                        print(f"PASS REPL {term} {width} columns: startup -> /help -> /quit: {elapsed:.3f}s", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        (output / "requests.json").write_text(json.dumps(RecordedProvider.requests, indent=2), encoding="utf-8")
    print(f"PASS all smoke scenarios: {time.perf_counter() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
