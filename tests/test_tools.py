"""Web tools, paid providers, jobs, orchestrator, compaction, shell."""

from __future__ import annotations

import json
import sys
import time
from unittest.mock import MagicMock

from kite.agent.cancel import CancelToken
from kite.agent.orchestrator import SubagentOrchestrator, evaluate_subagent_result, worker_glyph
from kite.context.observation import observation_content
from kite.context.window import compact_messages, scale_keep_recent_tokens, trim_stale_tool_messages
from kite.env.shell import resolve_shell_invocation, sanitize_shell_line
from kite.memory.compaction_ops import run_compaction
from kite.tools import web
from kite.tools.coding import make_coding_tools
from kite.tools.jobs import JobRegistry
from kite.tools.web_providers import resolve_search_engines, resolve_web_tool_env

DDG_FIXTURE = """
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="https://example.com/docs">Example Docs</a>
  <a class="result__snippet">Official documentation for the example library.</a>
</div>
<div class="result results_links results_links_deep web-result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ffoo">GitHub Repo</a>
  <a class="result__snippet">Source code on GitHub.</a>
</div>
"""


def test_paid_web_providers_chain(monkeypatch) -> None:
    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: "tvly-x")
    monkeypatch.setattr("kite.tools.web_providers.exa_api_key", lambda: "exa-x")
    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: "fc-x")
    assert resolve_search_engines("auto") == ["tavily", "exa", "firecrawl", "duckduckgo"]
    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: None)
    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: None)
    assert resolve_search_engines("auto") == ["exa", "duckduckgo"]
    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: "tvly-test")
    monkeypatch.setattr("kite.tools.web_providers.exa_api_key", lambda: None)

    def fake_json_post(url: str, *, headers=None, body=None, timeout=30):  # noqa: ANN001
        assert "tavily.com" in url
        return 200, {"results": [{"title": "Tavily Hit", "url": "https://example.com/a", "content": "Snippet from Tavily"}]}

    monkeypatch.setattr("kite.tools.web_providers._http_json", fake_json_post)
    monkeypatch.setattr(web, "_ddg_instant", lambda q: [])
    monkeypatch.setattr(web, "_ddg_html_search", lambda q: ("", "", "offline"))
    out = web.websearch("hello world", max_results=5)
    assert out["engine"] == "tavily" and out["results"][0]["title"] == "Tavily Hit"
    # Short paid results top up from DuckDuckGo, paid ranking kept first.
    monkeypatch.setattr(web, "_ddg_html_search", lambda q: (DDG_FIXTURE, "html", None))
    topped = web.websearch("hello world", max_results=5)
    assert topped["engine"] == "tavily+duckduckgo" and topped["topped_up"] is True
    assert topped["results"][0]["title"] == "Tavily Hit" and topped["count"] > 1
    monkeypatch.setattr("kite.tools.web_providers.tavily_api_key", lambda: "tvly-bad")
    monkeypatch.setattr("kite.tools.web_providers._http_json", lambda *_a, **_k: (401, {"error": "unauthorized"}))
    monkeypatch.setattr(web, "_ddg_instant", lambda q: [])
    monkeypatch.setattr(web, "_ddg_html_search", lambda q: (DDG_FIXTURE, "html", None))
    fallback = web.websearch("fallback query", max_results=3)
    assert fallback["engine"] == "duckduckgo"
    monkeypatch.setattr("kite.tools.web_providers.firecrawl_api_key", lambda: "fc-test")

    def fake_fc(url: str, *, headers=None, body=None, timeout=30):  # noqa: ANN001
        if "scrape" in url:
            return 200, {"success": True, "data": {"markdown": "# Hello\n\nWorld from Firecrawl", "metadata": {"title": "Hello", "description": "desc", "sourceURL": "https://example.com/"}}}
        if url.endswith("/crawl"):
            return 200, {"success": True, "id": "job-1"}
        return 200, {"success": True, "status": "completed", "data": [{"markdown": "page one", "metadata": {"sourceURL": "https://example.com/", "title": "Home"}}]}

    monkeypatch.setattr("kite.tools.web_providers._http_json", fake_fc)
    fetch = web.webfetch("https://example.com/")
    assert fetch.get("engine") == "firecrawl" and "World from Firecrawl" in fetch["output"]
    crawl = web.webcrawl("https://example.com/", max_pages=2, max_depth=1)
    assert crawl.get("engine") == "firecrawl"
    assert resolve_web_tool_env("tavily") == "TAVILY_API_KEY" and resolve_web_tool_env("unknown") is None


def test_submit_verification_background_jobs_and_orchestrator(tmp_path) -> None:
    from kite.agent.verification import VerificationCollector

    collector = VerificationCollector()
    collector.on_tool_end("edit", {"path": "a.py"}, {"ok": True, "path": "a.py", "diff": "d"})
    submit = next(
        t
        for t in make_coding_tools(cwd=str(tmp_path), enabled=["submit"], verification=collector)
        if t.name == "submit"
    )
    blocked = submit.run({"message": "finished"})
    assert blocked.get("blocked") is True and "Submit blocked" in str(blocked.get("error") or "")
    relaxed = next(
        t
        for t in make_coding_tools(
            cwd=str(tmp_path), enabled=["submit"], verification=collector, verify_before_submit=False
        )
        if t.name == "submit"
    )
    assert relaxed.run({"message": "finished"}).get("ok") is True

    script = "import sys; [sys.stdout.write('x'*40+'\\n') for _ in range(20000)]"
    reg = JobRegistry()
    job = reg.spawn_bash(f"{sys.executable} -c {json.dumps(script)}", cwd=str(tmp_path), timeout_seconds=8)
    deadline = time.monotonic() + 7
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job.status == "done"

    seen: dict[str, float] = {}

    class _Jobs:
        def spawn_bash(self, command, *, cwd, env=None, timeout_seconds=3600.0):
            seen["timeout"] = timeout_seconds

            class _Job:
                id = "j1"
                pid = 1

            return _Job()

    bash = next(t for t in make_coding_tools(cwd=str(tmp_path), jobs=_Jobs(), enabled=["bash"], auto_venv=False) if t.name == "bash")
    out = bash.run({"command": "echo hi", "background": True, "timeout": 12})
    assert out["ok"] is True and seen["timeout"] == 12.0

    sleep = f'{sys.executable} -c "import time; time.sleep(60)"'
    reg2 = JobRegistry()
    job2 = reg2.spawn_bash(sleep, cwd=str(tmp_path))
    assert job2.status == "running" and reg2.kill(job2.id) is True
    a = reg2.spawn_bash(sleep, cwd=str(tmp_path))
    b = reg2.spawn_bash(sleep, cwd=str(tmp_path))
    assert reg2.kill_all() == 2 and a.status == "killed" and b.status == "killed"
    token = CancelToken()
    sub = reg2.register_subagent(label="worker-1", prompt="do stuff", cancel=token)
    assert reg2.kill(sub.id) is True and token.is_set()
    events: list[str] = []
    live = JobRegistry(on_event=lambda e: events.append(e.kind))
    short = live.spawn_bash(f'{sys.executable} -c "print(1)"', cwd=str(tmp_path))
    deadline = time.monotonic() + 5
    while short.status == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "job_start" in events
    assert worker_glyph(1) == "◆" and worker_glyph(7) == worker_glyph(1)
    ok, quality, summary = evaluate_subagent_result({"exit_status": "Submitted", "submission": "all good"})
    assert ok and quality == "done" and summary == "all good"
    assert evaluate_subagent_result({"exit_status": "Error", "error": "boom"})[0] is False
    orch = SubagentOrchestrator(runner=lambda prompt, *, cancel=None: {"exit_status": "Submitted", "submission": f"done: {prompt[:20]}"}, timeout_seconds=0)
    one = orch.run_one("explore auth module", label="scout")
    assert one["ok"] is True
    parallel = SubagentOrchestrator(
        runner=lambda prompt, *, cancel=None: {"exit_status": "Error", "error": "nope"} if "fail" in prompt else {"exit_status": "Submitted", "submission": prompt},
        max_workers=2,
        timeout_seconds=0,
    ).run_parallel(["scan a", "scan fail", "scan b"], labels=["alpha", "broken", "beta"])
    assert parallel["succeeded"] == 2 and parallel["ok"] is False
    assert SubagentOrchestrator(runner=MagicMock()).dispatch({})["ok"] is False


def test_token_efficiency_registry_order_and_sparse_numbers(tmp_path) -> None:
    from kite.tools import Tool, ToolRegistry

    def _mk(name: str) -> Tool:
        return Tool(name, name, {"type": "object", "properties": {}}, lambda _a: {"ok": True})

    reg = ToolRegistry([_mk("write"), _mk("bash"), _mk("read")])
    assert [t.name for t in reg.list()] == ["bash", "read", "write"]
    assert [s["function"]["name"] for s in reg.tool_schemas()] == ["bash", "read", "write"]

    target = tmp_path / "code.py"
    # Pin LF bytes: Windows text-mode writes would translate \n to \r\n.
    target.write_bytes("".join(f"line {i}\n" for i in range(1, 31)).encode("utf-8"))
    read = next(t for t in make_coding_tools(cwd=str(tmp_path), enabled=["read"]) if t.name == "read")
    out = read.run({"path": str(target), "numbered": True})
    assert out["ok"] is True
    body = str(out["output"])
    # Sparse: first line + every 10th file line numbered, middle lines raw.
    assert "     1|line 1" in body
    assert "    11|line 11" in body
    assert "    21|line 21" in body
    assert "line 2\n" in body and "     2|line 2" not in body


def test_token_efficiency_spill_tiers_and_errors(tmp_path) -> None:
    from kite.context.spill import spill_text
    from kite.tools.errors import ToolErrorLedger, classify_tool_error
    from kite.tools.tiers import offload_manifest, partition_tools

    small = spill_text("x" * 100, cwd=str(tmp_path))
    assert small["spilled"] is False
    big = spill_text("y\n" * 8000, cwd=str(tmp_path), prefix="bash")
    assert big["spilled"] is True and "tail" not in str(big["path"])
    assert "grep" in str(big["output"]) and (tmp_path / ".kite" / "spills").is_dir()

    static, off = partition_tools(["read", "bash", "websearch", "memory"], enabled=False)
    assert off == [] and len(static) == 4
    static2, off2 = partition_tools(["read", "bash", "websearch", "memory"], enabled=True)
    assert static2 == ["read", "bash"] and sorted(off2) == ["memory", "websearch"]
    assert "web:" in offload_manifest(off2)

    assert classify_tool_error("read", {}, {"ok": False, "error": "not found: /x"}) == "invalid_arguments"
    assert classify_tool_error("bash", {}, {"ok": False, "error": "timeout after 5s"}) == "timeout"
    assert classify_tool_error("bash", {}, {"ok": False, "error": "weird boom xyz"}) == "unknown"
    ledger = ToolErrorLedger()
    ledger.record("bash", {"ok": False, "error": "weird boom xyz"}, model="m1")
    assert ledger.error_rate("bash") == 1.0 and ledger.summary()["unexpected"] == {"bash": 1}


def test_observation_compaction_and_shell() -> None:
    raw = "x" * 20_000
    out = observation_content({"ok": True, "output": raw, "summary": "42 lines matched in src/app.py"}, max_chars=2_000)
    assert "42 lines matched" in out and "elided" in out.lower()
    assert observation_content({"output": "hello world"}, max_chars=8_000) == "hello world"
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a" * 500},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "read"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "file body"},
        {"role": "user", "content": "tail question"},
        {"role": "assistant", "content": "answer"},
    ]
    compacted = compact_messages(msgs, keep_recent_tokens=80, force=True)
    roles = [m["role"] for m in compacted]
    if "tool" in roles:
        assert roles[roles.index("tool") - 1] == "assistant"
    assert scale_keep_recent_tokens(128_000, 12_000) == 12_000
    big = "x\n" * 2000
    trimmed = trim_stale_tool_messages(
        [
            {"role": "user", "content": "old task"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "bash"}}]},
            {"role": "tool", "tool_call_id": "1", "content": big},
            {"role": "user", "content": "new task"},
            {"role": "assistant", "content": "ok"},
        ],
        keep_recent_segments=1,
    )
    tool = next(m for m in trimmed if m.get("role") == "tool")
    assert len(str(tool.get("content") or "")) < len(big)
    calls: list[str] = []
    result = run_compaction(
        [{"role": "system", "content": "s"}] + [{"role": "user", "content": "word " * 20_000}] * 4 + [{"role": "user", "content": "z"}],
        window=128_000,
        reserve_tokens=16_384,
        keep_recent_tokens=500,
        force=True,
        summarizer=lambda _dropped: calls.append("llm") or "llm summary",
        compaction_llm_ratio=0.99,
    )
    assert result.compacted and calls == []
    old_tool = "y" * 5000
    trimmed_only = [{"role": "user", "content": "old"}]
    for i in range(4):
        trimmed_only.extend(
            [
                {"role": "assistant", "content": "", "tool_calls": [{"id": str(i), "function": {"name": "bash"}}]},
                {"role": "tool", "tool_call_id": str(i), "content": old_tool},
            ]
        )
    trimmed_only.append({"role": "user", "content": "new"})
    trim_result = run_compaction(
        trimmed_only,
        window=8_000,
        reserve_tokens=1_000,
        compact_ratio=0.95,
        force=False,
        checkpoint_before=False,
    )
    assert trim_result.compacted and trim_result.messages != trimmed_only
    assert sanitize_shell_line("hello\r\nworld\t!") == "hello world !"
    argv, cmd = resolve_shell_invocation("pytest -q")
    if sys.platform != "win32":
        assert argv is None and cmd == "pytest -q"


def _summarize_cfg(**overrides):
    from kite.config.user import UserConfig

    base = {
        "default_provider": "openai",
        "default_model": "gpt-4o-mini",
        "compaction_provider": "openrouter",
        "compaction_model": None,
        "compaction_use_llm": True,
        "compaction_fallback_session": True,
    }
    base.update(overrides)
    return UserConfig(**base)


def _stub_session_fallback(monkeypatch, *, complete_result="session summary", creds_ok=True):  # noqa: ANN001, ANN202
    """Empty free-tier list + stubbed resolve/creds/complete. Returns (summ, calls, tried)."""
    from types import SimpleNamespace

    from kite.agent import summarize as summ

    monkeypatch.setattr(summ, "list_compaction_models", lambda _cfg: [])
    calls: list[tuple] = []
    tried: list[tuple] = []

    def fake_resolve(*, provider=None, model=None, config=None, catalog=None):  # noqa: ANN001
        calls.append((provider, model))
        return SimpleNamespace(provider=provider or "openai", model=model or "gpt-4o-mini")

    def fake_complete(resolved, _transcript):  # noqa: ANN001
        tried.append((resolved.provider, resolved.model))
        return complete_result

    monkeypatch.setattr("kite.providers.resolve.resolve_model", fake_resolve)
    monkeypatch.setattr("kite.providers.resolve.missing_credentials", lambda _r: None if creds_ok else "need key")
    monkeypatch.setattr(summ, "_try_complete", fake_complete)
    return summ, calls, tried


def test_llm_summarize_session_fallback_matrix(monkeypatch) -> None:
    summ, calls, _tried = _stub_session_fallback(monkeypatch)
    out = summ.llm_summarize([{"role": "user", "content": "hello"}], config=_summarize_cfg())
    assert out == "session summary"
    assert ("openai", "gpt-4o-mini") in calls

    summ2, _calls2, tried2 = _stub_session_fallback(monkeypatch)
    out2 = summ2.llm_summarize(
        [{"role": "user", "content": "hello"}],
        config=_summarize_cfg(compaction_fallback_session=False),
    )
    assert out2 is None and tried2 == []

    summ3, _calls3, tried3 = _stub_session_fallback(monkeypatch, creds_ok=False)
    out3 = summ3.llm_summarize([{"role": "user", "content": "hello"}], config=_summarize_cfg())
    assert out3 is None and tried3 == []

    summ4, calls4, _tried4 = _stub_session_fallback(monkeypatch)
    out4 = summ4.llm_summarize(
        [{"role": "user", "content": "hello"}],
        config=_summarize_cfg(),
        session_provider="anthropic",
        session_model="claude-x",
    )
    assert out4 == "session summary"
    assert ("anthropic", "claude-x") in calls4


def test_llm_summarize_no_duplicate_session_attempt(monkeypatch) -> None:
    from types import SimpleNamespace

    from kite.agent import summarize as summ

    cfg = _summarize_cfg(
        default_provider="openrouter",
        default_model="m1",
        compaction_provider="openrouter",
        compaction_model="m1",
    )
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda *, provider=None, model=None, config=None, catalog=None: SimpleNamespace(
            provider=provider or "openrouter", model=model or "m1"
        ),
    )
    monkeypatch.setattr("kite.providers.resolve.missing_credentials", lambda _r: None)
    tried: list[tuple] = []
    monkeypatch.setattr(summ, "_try_complete", lambda r, _t: tried.append((r.provider, r.model)) or None)
    assert summ.llm_summarize([{"role": "user", "content": "hello"}], config=cfg) is None
    assert tried == [("openrouter", "m1")]


def test_make_summarizer_forwards_session_overrides(monkeypatch) -> None:
    from kite.agent import summarize as summ

    seen: dict = {}

    def fake_llm(messages, *, config=None, session_provider=None, session_model=None):  # noqa: ANN001
        seen["session_provider"] = session_provider
        seen["session_model"] = session_model
        return "llm text"

    monkeypatch.setattr(summ, "llm_summarize", fake_llm)
    summarize = summ.make_summarizer(_summarize_cfg(), session_provider="groq", session_model="llama-x")
    assert summarize([{"role": "user", "content": "hi"}]) == "llm text"
    assert (seen["session_provider"], seen["session_model"]) == ("groq", "llama-x")

def test_subagent_parent_plan_context_attached() -> None:
    from kite.tools.coding import _with_parent_plan_context

    class _Store:
        def read(self):
            return [
                {"status": "pending", "content": "write tests"},
                {"status": "in_progress", "content": "fix login bug"},
            ]

    out = _with_parent_plan_context({"prompt": "help out"}, _Store())
    assert "fix login bug" in out["context"] and "write tests" in out["context"]
    # In-progress sorts first; explicit context always wins.
    assert out["context"].index("fix login bug") < out["context"].index("write tests")
    explicit = _with_parent_plan_context({"prompt": "x", "context": "mine"}, _Store())
    assert explicit["context"] == "mine"
    assert _with_parent_plan_context({"prompt": "x"}, None)["prompt"] == "x"
