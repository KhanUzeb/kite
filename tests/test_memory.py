"""Sessions, continuity, user context, working style, prompts."""

from __future__ import annotations

import json
import stat
import sys
import time

import pytest

from kite.agent.loop import DefaultAgent
from kite.agent.subagent_profiles import (
    get_profile,
    init_user_profile,
    list_profiles,
    profiles_for_orchestrator,
    resolve_subagent_task,
)
from kite.config import load_runtime_config
from kite.config.interactive_budget import effective_agent_limits, resolve_interactive_limits
from kite.config.runtime import AgentRuntimeConfig, MemoryConfig
from kite.config.user import UserConfig
from kite.memory.continuity import (
    build_continuity_brief,
    format_continuity_section,
    latest_continuity_markdown,
    next_budget_action,
    record_continuity_after_compact,
    save_continuity,
    should_budget_auto_continue,
)
from kite.memory.session import create_session, format_meta_line, list_sessions, load_session
from kite.memory.session_analytics import SessionStats, save_session_stats, scan_session_file
from kite.memory.session_format import (
    format_session_picker_label,
    format_session_resume_hint,
    format_session_when,
    match_sessions,
    session_title,
    suggest_sessions,
)
from kite.memory.store import MemoryStore
from kite.memory.user_context import (
    append_profile_note,
    append_user_note,
    profile_path,
    read_profile,
    read_user,
    render_user_context,
    user_path,
)
from kite.memory.working_style import (
    append_signal,
    format_working_section,
    infer_style_signals,
    observe_session_turn,
    render_working_context,
)
from kite.prompts import assemble_system_prompt, discover_system_prompt_files, load_prompt_template
from kite.ui.budget_continue import decide_budget_continue


class _StubModel:
    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages):
        return {"role": "assistant", "content": "hello", "extra": {"actions": [], "cost": 0.0}}

    def format_observation_messages(self, message, outputs, template_vars=None):
        return []


class _StubEnv:
    def execute(self, action, cwd=""):
        return {"ok": True, "output": ""}


def test_session_append_compact_and_stats(kite_home, tmp_path) -> None:
    session = create_session(task="demo", cwd=str(tmp_path), provider="groq", model="test")
    session.append({"role": "user", "content": "hi"})
    session.append({"role": "assistant", "content": "hello"})
    lines = session.path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["type"] == "meta"
    assert sum(1 for ln in lines if '"type": "message"' in ln) == 2
    first = format_meta_line(session.meta)
    session.meta.updated_at = session.meta.updated_at + 1
    assert len(first) == len(format_meta_line(session.meta))
    for i in range(5):
        session.append({"role": "user", "content": f"turn {i}" * 50})
    size_before = session.path.stat().st_size
    session.replace_messages([{"role": "user", "content": "Previous conversation summary:\ncompacted"}, {"role": "assistant", "content": "recent"}])
    assert session.path.stat().st_size < size_before
    loaded = load_session(session.id)
    assert len(loaded.messages) == 2
    save_session_stats(SessionStats(session_id=session.id, created_at=1.0, updated_at=10.0, duration_s=9.0, provider="groq", model="test", cwd=str(tmp_path), tool_calls=3, tool_counts={"read": 2}, api_calls=5, cost=0.12, estimated_tokens=4000, cache_hit_tokens=800))
    row = scan_session_file(session.save())
    assert row is not None and row.tool_calls == 3
    session.record_event("compact", {"before": 10, "after": 4})
    session.record_event("tool_end", {"tool": "edit", "ok": False, "blocked": True})
    scanned = scan_session_file(session._session_path())
    assert scanned.compaction_count == 1 and scanned.tool_blocked == 1


def test_session_persistence_modes(kite_home) -> None:
    cfg = UserConfig.load()
    cfg.session_persistence = "redacted"
    cfg.save()
    session = create_session(task="secret", cwd="/tmp", provider="p", model="m")
    session.append({"role": "user", "content": "Bearer SECRETTOKEN", "headers": {"Authorization": "Bearer SECRETTOKEN"}})
    text = session.path.read_text(encoding="utf-8")
    assert "SECRETTOKEN" not in text and "[REDACTED]" in text
    if sys.platform != "win32":
        assert session.path.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR
    cfg.session_persistence = "full"
    cfg.save()
    full = create_session(task="full", cwd="/tmp", provider="p", model="m")
    full.append({"role": "user", "content": "Bearer FULLMODE-SECRET"})
    assert "FULLMODE-SECRET" in full.path.read_text(encoding="utf-8")
    cfg.session_persistence = "disabled"
    cfg.save()
    off = create_session(task="off", cwd="/tmp", provider="p", model="m")
    off.append({"role": "user", "content": "hello"})
    assert not off.path.is_file() or off.path.stat().st_size == 0


def test_session_format_and_search(kite_home) -> None:
    session = create_session(task="long task text", cwd="/tmp", provider="p", model="m", label="Humanize docs")
    assert session_title(session.meta) == "Humanize docs"
    _, _, rel = format_session_when(time.time() - 120, now=time.time())
    assert rel == "2m ago"
    create_session(task="beta", cwd="/tmp", provider="p", model="m", label="tests only")
    matched = match_sessions(list_sessions(limit=10), "docs")
    assert len(matched) == 1
    labeled = create_session(task="ship it", cwd="/tmp/kite", provider="groq", model="llama", label="ship")
    label = format_session_picker_label(labeled.meta)
    assert "groq/llama" in label
    hint = format_session_resume_hint(session.meta)
    assert "Humanize docs" in hint or "long task" in hint
    short = session.id.split("-")[-1]
    assert any(row.id == session.id for row in suggest_sessions(short, limit=3))


def test_continuity_budget_and_memory_opt_in(workspace, kite_home) -> None:
    brief = build_continuity_brief(messages=[{"role": "user", "content": "Add auth tests"}], todos=[{"status": "in_progress", "content": "write failing test"}], task="Add auth tests")
    assert "Add auth tests" in brief.to_markdown()
    assert should_budget_auto_continue(exit_status="LimitsExceeded", continues_used=0, max_continues=2, todos=[{"status": "pending", "content": "x"}], tool_call_count=2, inbox_queued=False)
    assert not should_budget_auto_continue(exit_status="LimitsExceeded", continues_used=0, max_continues=2, todos=[{"status": "pending", "content": "x"}], tool_call_count=2, inbox_queued=True)
    assert next_budget_action(exit_status="LimitsExceeded", continues_used=0, max_continues=2, todos=[{"status": "pending", "content": "x"}], tool_call_count=1, inbox_queued=False) == "continue"
    store = MemoryStore.open(workspace)
    md = record_continuity_after_compact(store=store, messages=[{"role": "user", "content": "Ship the fix"}], todos=[{"status": "in_progress", "content": "add regression test"}], session_id="sess1", cwd=str(workspace), task="Ship the fix")
    assert "## Continuity" in md and "Ship the fix" in latest_continuity_markdown(store, session_id="sess1")
    assert decide_budget_continue(exit_status="LimitsExceeded", continues_used=0, max_continues=2, todos=[{"status": "pending", "content": "x"}], tool_call_count=2, inbox_queued=False) == "continue"
    assert decide_budget_continue(exit_status="LimitsExceeded", continues_used=2, max_continues=2, todos=[{"status": "pending", "content": "x"}], tool_call_count=2, inbox_queued=False) == "stop"
    store.remember("prefer ruff", scope="project")
    cfg = AgentRuntimeConfig(memory=MemoryConfig(inject="opt_in"))
    assert "# Memory" not in assemble_system_prompt(config=cfg, memory="", continuity="")
    system = assemble_system_prompt(config=cfg, memory=store.render_for_prompt(), continuity="")
    assert "# Memory" in system and "prefer ruff" in system
    assert "# Memory" not in format_continuity_section("## Continuity\n- Mission: ship fix")
    save_continuity(store=store, brief=brief, session_id="s1", cwd=str(workspace))
    steps, cost = resolve_interactive_limits(interactive=True, user_step=40, user_cost=5.0, runtime_step=40, runtime_cost=5.0)
    assert steps == 80 and cost == 10.0
    low_s, low_c = resolve_interactive_limits(interactive=True, user_step=20, user_cost=1.0, runtime_step=20, runtime_cost=1.0)
    assert low_s == 20 and low_c == 1.0
    long_s, long_c = effective_agent_limits(interactive=False, options_step=None, options_cost=None, runtime_step=40, runtime_cost=5.0, user_step=40, user_cost=5.0, interactive_step=80, interactive_cost=10.0, long_task=True)
    assert long_s == 120 and long_c == 25.0


def test_user_context_profiles_and_working_style(workspace, kite_home) -> None:
    assert user_path().name == "USER.md" and profile_path().name == "PROFILE.md"
    append_user_note("prefers pytest")
    append_profile_note("Python backend focus")
    assert "prefers pytest" in read_user() and "Python backend focus" in read_profile()
    store = MemoryStore.open(workspace)
    append_signal("likes small diffs")
    rendered = render_user_context(store)
    assert "Working rhythm" in rendered
    assert "small diffs" in rendered
    cfg = AgentRuntimeConfig(memory=MemoryConfig(inject="opt_in"))
    system = assemble_system_prompt(config=cfg, memory="", working_style=render_working_context(store), continuity="")
    assert "Working rhythm" in system and "# Memory" not in system
    ids = {p.id for p in list_profiles()}
    assert "scout" in ids and "coder" in ids
    composed, role, label = resolve_subagent_task(prompt="find auth module", profile="scout", role="", label="")
    assert "find auth module" in composed and role == "architect"
    assert "scout" in profiles_for_orchestrator()
    assert get_profile("nonexistent-xyz") is None
    path = init_user_profile("my-auditor", label="Auditor", role="debugger", description="Security-focused review")
    assert path.is_file() and get_profile("my-auditor").label == "Auditor"
    with pytest.raises(ValueError, match="invalid profile id"):
        init_user_profile("!!!")
    from kite.cli.run import build_parser

    args = build_parser().parse_args(["subagents", "--init", "reviewer-custom", "--role", "debugger"])
    assert args.init == "reviewer-custom"
    assert infer_style_signals(mode="plan", write_edits=5, bash_calls=4)
    observe_session_turn(store, session_id="s1", mode="plan", approval="readonly", extra={"exit_status": "Submitted", "model_stats": {"write_edits": 6, "bash_calls": 1}})
    assert "Working rhythm" in format_working_section("### Signals\n- tends to plan first")
    assert "untrusted" in format_working_section("### Signals\n- tends to plan first").lower()


def test_prompts_keep_chat_literal(tmp_path, monkeypatch) -> None:
    agent = DefaultAgent(_StubModel(), _StubEnv(), instance_prompt="Please solve this task:\n\n{task}\nInspect before editing.", interactive=True)
    text = agent._user_turn_text("hi", follow="hi", kwargs={})
    assert text == "hi" and "Please solve this task" not in text
    oneshot = DefaultAgent(_StubModel(), _StubEnv(), instance_prompt="TASK:{task}", interactive=False)
    assert oneshot._user_turn_text("hi", follow="hi", kwargs={}) == "TASK:hi"
    assembled = assemble_system_prompt(config=load_runtime_config())
    assert "## Effort" in assembled and "## Credentials & secrets" in assembled and "## Skills (trust & supply chain)" in assembled
    home = tmp_path / "kite_home"
    home.mkdir()
    monkeypatch.setenv("KITE_HOME", str(home))
    (home / "SYSTEM.md").write_text("GLOBAL BASE", encoding="utf-8")
    project = tmp_path / "proj"
    (project / ".kite").mkdir(parents=True)
    (project / ".kite" / "SYSTEM.md").write_text("PROJECT BASE", encoding="utf-8")
    override, _append = discover_system_prompt_files(project)
    assert override == "PROJECT BASE" and load_prompt_template("system")
