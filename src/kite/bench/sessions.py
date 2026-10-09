"""Opt-in session scale workloads; all files live in an isolated temporary Kite home."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from kite.bench.suite import BenchmarkResult, _sample
from kite.bench.timing import measure_many


def run_session_suite(root: Path) -> list[BenchmarkResult]:
    from kite.config import ensure_home
    from kite.config.user import _invalidate_user_config_cache
    from kite.memory.session import (
        SessionMeta,
        create_session,
        format_meta_line,
        list_sessions,
        load_session,
        load_session_tail,
    )
    from kite.memory.session_analytics import list_session_events

    home = root / "session-home"
    rows = []
    with patch.dict(os.environ, {"KITE_HOME": str(home)}):
        _invalidate_user_config_cache()
        try:
            ensure_home()
            folder = home / "sessions"
            for i in range(2000):
                sid = f"scale-{i:04}"
                meta = SessionMeta(sid, 1_700_000_000 + i, 1_700_000_000 + i, str(root), "bench", "stub", f"benchmark {i}")
                path = folder / f"{sid}.jsonl"
                path.write_text(format_meta_line(meta) + "\n", encoding="utf-8")
                os.utime(path, (meta.updated_at, meta.updated_at))
            found, sample = measure_many("session_list_2000", lambda: len(list_sessions(limit=30)), iterations=5)
            if found != 30:
                raise RuntimeError(f"session listing returned {found} rows, expected 30")
            rows.append(_sample("session_list_2000", "memory", sample, sessions=2000, limit=30, metadata_only=True))

            session = create_session(task="append benchmark", cwd=str(root), provider="bench", model="stub")
            payload = {"tool": "read", "ok": True, "path": "src/example.py", "result": "ordinary text " * 20}

            def append_events() -> None:
                for _ in range(500):
                    session.record_event("tool_end", payload)

            _, sample = measure_many("session_append_500", append_events, iterations=5)
            rows.append(_sample("session_append_500", "memory", sample, events=500, ms_per_event=sample.ms / 500))

            body = json.dumps({"type": "message", "message": {"role": "user", "content": "ordinary benchmark content " * 157}}) + "\n"
            large = folder / "large.jsonl"
            meta = SessionMeta("large", 1_700_000_000., 1_700_000_000., str(root), "bench", "stub", "50 MB resume")
            with large.open("w", encoding="utf-8") as handle:
                handle.write(format_meta_line(meta) + "\n")
                for _ in range(50_000_000 // len(body)):
                    handle.write(body)
                for i in range(30):
                    handle.write(json.dumps({"type": "event", "kind": "turn_start", "ts": i, "payload": {}}) + "\n")
            for name, fn in (
                ("session_resume_50mb", lambda: len(load_session("large").messages)),
                ("session_tail_50mb", lambda: len(load_session_tail("large", 60).messages)),
                ("session_recent_events", lambda: len(list_session_events(large, limit=20))),
            ):
                count, sample = measure_many(name, fn, iterations=5)
                rows.append(_sample(name, "memory", sample, file_bytes=large.stat().st_size, rows=count))

            long_row = folder / "long-row.jsonl"
            meta = SessionMeta("long-row", 1_700_000_000., 1_700_000_000., str(root), "bench", "stub", "single 50 MB row")
            with long_row.open("w", encoding="utf-8") as handle:
                handle.write(format_meta_line(meta) + "\n")
                handle.write(json.dumps({"type": "message", "message": {"role": "user", "content": "x" * 50_000_000}}) + "\n")
            count, sample = measure_many("session_reverse_row_50mb",
                lambda: len(load_session_tail("long-row", 1).messages[-1]["content"]), iterations=3)
            if count != 50_000_000:
                raise RuntimeError("reverse reader truncated the large session row")
            rows.append(_sample("session_reverse_row_50mb", "memory", sample, row_content_bytes=count))
        finally:
            _invalidate_user_config_cache()
    return rows
