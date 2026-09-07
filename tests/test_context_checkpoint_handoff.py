"""Context checkpoint, handoff, and improved compaction tests."""

from __future__ import annotations

from pathlib import Path

from kite.context.window import COMPACTION_PREFIX, compact_messages, extract_compaction_facts
from kite.memory.compaction_ops import run_compaction
from kite.memory.context_checkpoint import list_checkpoints, load_checkpoint, save_checkpoint
from kite.memory.handoff import build_handoff_markdown, write_handoff
from kite.memory.session import SessionMeta, create_session


def _messages_with_edit() -> list[dict]:
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Fix auth.py — must not break login"},
        {"role": "assistant", "content": "ok", "tool_calls": [{"function": {"name": "edit"}}]},
        {"role": "user", "content": "error: test_auth failed with AssertionError"},
        {"role": "assistant", "content": "retry"},
        {"role": "user", "content": "x" * 200},
        {"role": "assistant", "content": "y" * 200},
        {"role": "user", "content": "z" * 200},
    ]


def test_extract_compaction_facts():
    facts = extract_compaction_facts(_messages_with_edit())
    assert any("constraint" in f or "error" in f.lower() for f in facts)
    assert any("edit" in f for f in facts)


def test_compact_messages_includes_facts_block():
    msgs = _messages_with_edit()
    out = compact_messages(msgs, keep_recent_tokens=50, force=True)
    summary = next(m["content"] for m in out if str(m.get("content", "")).startswith(COMPACTION_PREFIX))
    assert "## Preserved facts" in summary
    assert summary.startswith(COMPACTION_PREFIX)


def test_save_and_load_checkpoint(kite_home: Path, tmp_path: Path):
    session = create_session(task="demo", cwd=str(tmp_path), provider="groq", model="test")
    messages = [{"role": "user", "content": "hello"}]
    cp = save_checkpoint(
        session_id=session.id,
        messages=messages,
        cwd=str(tmp_path),
        label="test",
    )
    loaded = load_checkpoint(session.id, cp.id)
    assert loaded.messages == messages
    rows = list_checkpoints(session.id)
    assert rows and rows[0].id == cp.id


def test_run_compaction_creates_checkpoint(kite_home: Path, tmp_path: Path):
    session = create_session(task="big", cwd=str(tmp_path), provider="groq", model="test")
    # inflate token estimate
    big = [{"role": "user", "content": "word " * 50_000}]
    msgs = [{"role": "system", "content": "s"}] + big + [{"role": "user", "content": "tail"}] * 8
    result = run_compaction(
        msgs,
        window=128_000,
        reserve_tokens=100_000,
        keep_recent_tokens=500,
        force=True,
        session_id=session.id,
        cwd=str(tmp_path),
        checkpoint_before=True,
        checkpoint_ratio=0.0,
    )
    assert result.compacted is True
    assert result.checkpoint is not None


def test_handoff_writes_files(kite_home: Path, workspace: Path):
    session = create_session(task="ship feature", cwd=str(workspace), provider="groq", model="test")
    session.messages = [
        {"role": "user", "content": "implement handoff"},
        {"role": "assistant", "content": "done"},
    ]
    bundle = write_handoff(session=session, cwd=str(workspace), todos=[{"status": "in_progress", "content": "tests"}])
    assert bundle.markdown_path is not None
    assert bundle.markdown_path.is_file()
    assert bundle.json_path is not None
    assert bundle.json_path.is_file()
    text = bundle.markdown_path.read_text(encoding="utf-8")
    assert "Kite Agent Handoff" in text
    assert session.id in text


def test_build_handoff_markdown():
    meta = SessionMeta(
        id="sess-1",
        created_at=1.0,
        updated_at=1.0,
        cwd="/tmp",
        provider="groq",
        model="llama",
        task="fix bug",
    )
    md = build_handoff_markdown(
        meta=meta,
        messages=[{"role": "user", "content": "fix the auth bug"}],
        cwd="/tmp",
        checkpoint_id="cp-abc",
    )
    assert "kite resume sess-1" in md
    assert "cp-abc" in md
