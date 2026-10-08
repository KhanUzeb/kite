"""Session reset, usage reports, resume cards, and bundled prompt expansion."""

from __future__ import annotations

import json
from io import StringIO

from rich.console import Console


def _chat(workspace, monkeypatch, **kwargs):
    from kite.ui.repl import ChatSession

    monkeypatch.setattr("kite.models.litellm_model.prewarm_litellm", lambda: None)
    monkeypatch.setattr(ChatSession, "_warm_auth_probes", lambda self: None)
    chat = ChatSession(cwd=str(workspace), **kwargs)
    buf = StringIO()
    chat.console = Console(file=buf, force_terminal=False, width=100)
    return chat, buf


def test_new_resets_session_usage_and_queue_but_preserves_model(workspace, kite_home, monkeypatch) -> None:
    chat, buf = _chat(workspace, monkeypatch, provider="groq", model="llama-3.3-70b-versatile")
    chat._session_id = "sess-old"
    chat.state.cost = 1.25
    chat.state.n_calls = 7
    chat.state.usage_input_tokens = 100
    chat.state.usage_output_tokens = 50
    chat.state.usage_cache_read_tokens = 30
    chat.state.usage_cache_write_tokens = 10
    chat.state.tokens = 500
    chat.state.window = 128000
    chat._inbox.enqueue("pending follow-up")
    assert chat._handle_slash("/new") is True
    out = buf.getvalue()
    assert "Started a new session." in out
    assert chat._session_id is None
    assert chat.state.cost == 0.0 and chat.state.n_calls == 0
    assert chat.state.usage_input_tokens == 0 and chat.state.usage_output_tokens == 0
    assert chat.state.usage_cache_read_tokens == 0 and chat.state.usage_cache_write_tokens == 0
    assert chat.state.tokens == 0 and len(chat._inbox) == 0
    assert chat.provider == "groq" and chat.model == "llama-3.3-70b-versatile"


def test_usage_reports_json_and_format(workspace, kite_home, monkeypatch) -> None:
    from kite.models.usage import format_usage_report

    chat, buf = _chat(workspace, monkeypatch, provider="groq", model="m")
    chat._slash_usage("")
    out = buf.getvalue()
    assert "Usage" in out and "Session" in out and "Context" in out and "Providers" in out
    assert "Input tokens:" in out and "Cost:" in out
    assert "available if supported" in out  # no quota API — never an error

    chat.state.usage_input_tokens = 12430
    chat.state.usage_output_tokens = 4210
    chat.state.usage_cache_read_tokens = 8900
    chat.state.usage_cache_write_tokens = 1200
    chat.state.n_calls = 14
    chat.state.cost = 0.0842
    chat.state.tokens = 16300
    chat.state.window = 128000
    buf.truncate(0)
    buf.seek(0)
    chat._slash_usage("session")
    out = buf.getvalue()
    assert "12,430" in out and "4,210" in out and "8,900" in out and "1,200" in out
    assert "17,840" in out and "$0.0842" in out and "12.7%" in out

    buf.truncate(0)
    buf.seek(0)
    chat._slash_usage("--json")
    payload = json.loads(buf.getvalue())
    assert payload["total_tokens"] == 17840 and payload["provider"] == "groq" and payload["quota"] is None
    buf.truncate(0)
    buf.seek(0)
    chat._slash_usage("bogus")
    assert "usage" in buf.getvalue().lower()

    report = format_usage_report(
        input_tokens=10, output_tokens=5, cache_read_tokens=3, cache_write_tokens=2,
        cost=0.5, context_tokens=100, context_window=1000,
        provider="groq", quota={"rate_limit": "60 req/min", "resets": "12:00"},
    )
    assert report["total_tokens"] == 17 and "60 req/min" in report["text"]


def test_resume_picker_cards_scan_truncate_and_group(workspace, monkeypatch) -> None:
    import time

    from kite.memory.session import SessionMeta
    from kite.memory.session_format import (
        format_session_card,
        format_session_picker_label,
        group_sessions_by_scope,
    )
    from kite.ui.tables import render_sessions_table

    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
    now = time.time()
    here = SessionMeta(
        id="20240101-120000-aaaabbbb", created_at=now - 36000, updated_at=now - 36000,
        cwd=str(workspace), provider="groq", model="llama", task="x" * 200,
        label="Explain RL and truncation feedback", exit_status="done",
    )
    away = SessionMeta(
        id="20240101-120000-ccccdddd", created_at=now - 90000, updated_at=now - 90000,
        cwd="/other/project", provider="p", model="m", task="other work",
        label="Assess model competence", exit_status="open",
    )
    label = format_session_picker_label(here)
    assert label.index("Explain RL") < label.index("groq/llama")  # prompt first
    prompt_line, _ = format_session_card(here, width=30)
    assert len(prompt_line) <= 32 and prompt_line.endswith("…")
    _, full_meta = format_session_card(here, width=120)
    assert "done" in full_meta and "groq/llama" in full_meta
    current, rest = group_sessions_by_scope([away, here], str(workspace))
    assert [m.id for m in current] == [here.id] and [m.id for m in rest] == [away.id]

    buf = StringIO()
    render_sessions_table(Console(file=buf, force_terminal=False, width=60), [], title="T")
    assert "no sessions" in buf.getvalue()
    buf = StringIO()
    render_sessions_table(
        Console(file=buf, force_terminal=False, width=100), [here, away],
        title="Resume Session (current folder)", current=here.id,
    )
    out = buf.getvalue()
    assert "Explain RL and truncation feedback" in out and "Assess model competence" in out
    assert "Resume Session (current folder)" in out


def test_unslop_bundled_command_expands_user_arguments(workspace, kite_home) -> None:
    from kite.cli.slash import CommandIndex

    index = CommandIndex.load(workspace)
    expanded = index.expand("unslop", "this README")
    assert expanded and "this README" in expanded and "behavior" in expanded.lower()
