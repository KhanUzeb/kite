# Adaptive Budget + Smart Continuity Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interactive chat gets deeper default budgets, ≤2 auto-continues on `LimitsExceeded` with unfinished work, and Codex/Pi-style continuity briefs that survive compact/continue — without infinite loops.

**Architecture:** Pure helpers in `kite.memory.continuity` build/store/decide continues. `AgentRuntime` applies interactive budget floors and injects the latest continuity brief into prompt assembly. Compaction path records a continuity episode after a successful compact. `ChatSession._run_task` owns the capped auto-continue loop (inbox wins; soft-pause after 2).

**Tech Stack:** Python 3.11+, existing `MemoryStore` / episodic SQLite, `Harness`/`AgentRuntime`, pytest (no live LLM).

**Spec:** `docs/superpowers/specs/2026-09-06-adaptive-budget-smart-memory-design.md`

## Global Constraints

- Interactive floors: 80 steps / $10.0 when still on package defaults (40 / 5.0); honor explicit lower user caps
- `max_budget_continues = 2` per user-initiated turn chain
- Never auto-continue on `Submitted`, `Interrupted`, `Stalled`, `ProviderFault`, LoopGuard hard-stop
- If REPL inbox has queued text, drain inbox instead of silent auto-continue
- Default `compaction_ratio` 0.80 → 0.75; checkpoint stays ~0.72
- Non-interactive `kite run` defaults unchanged unless flags say otherwise
- Small diffs; update `docs/cli-ux.md` for user-facing behavior; run pytest on touched areas
- Do not commit unless the user asks (ignore “Commit” steps or stop before them)

---

### Task 1: Continuity helpers (build / unfinished / auto-continue gate)

**Files:**
- Create: `src/kite/memory/continuity.py`
- Test: `tests/test_continuity.py`

**Interfaces:**
- Produces:
  - `ContinuityBrief` dataclass with fields `mission`, `done`, `next_steps`, `constraints`, `paths`, `todos` (lists/str) and `to_markdown() -> str`
  - `build_continuity_brief(*, messages: list[dict], todos: list[dict] | None, task: str = "") -> ContinuityBrief`
  - `has_unfinished_work(*, todos: list[dict] | None, exit_status: str, tool_call_count: int = 0) -> bool`
  - `should_budget_auto_continue(*, exit_status: str, continues_used: int, max_continues: int, todos: list[dict] | None, tool_call_count: int, inbox_queued: bool) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_continuity.py
from kite.memory.continuity import (
    build_continuity_brief,
    has_unfinished_work,
    should_budget_auto_continue,
)


def test_build_continuity_brief_includes_mission_and_todos() -> None:
    messages = [
        {"role": "user", "content": "Add auth tests"},
        {"role": "assistant", "content": "Edited tests/test_auth.py"},
    ]
    todos = [{"status": "in_progress", "content": "write failing test"}]
    brief = build_continuity_brief(messages=messages, todos=todos, task="Add auth tests")
    md = brief.to_markdown()
    assert "## Continuity" in md
    assert "Add auth tests" in md
    assert "write failing test" in md


def test_has_unfinished_work_open_todos() -> None:
    assert has_unfinished_work(
        todos=[{"status": "pending", "content": "x"}],
        exit_status="LimitsExceeded",
        tool_call_count=3,
    )


def test_has_unfinished_work_false_when_submitted() -> None:
    assert not has_unfinished_work(
        todos=[{"status": "completed", "content": "x"}],
        exit_status="Submitted",
        tool_call_count=5,
    )


def test_should_budget_auto_continue_caps_and_inbox() -> None:
    assert should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=False,
    )
    assert not should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=2,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=False,
    )
    assert not should_budget_auto_continue(
        exit_status="LimitsExceeded",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=True,
    )
    assert not should_budget_auto_continue(
        exit_status="Interrupted",
        continues_used=0,
        max_continues=2,
        todos=[{"status": "pending", "content": "x"}],
        tool_call_count=2,
        inbox_queued=False,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_continuity.py -q --tb=line`  
Expected: FAIL (module/import not found)

- [ ] **Step 3: Implement `src/kite/memory/continuity.py`**

```python
"""Codex/Pi-style continuity briefs for compact + budget continue."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kite.context.window import COMPACTION_PREFIX

_STOP_EXITS = frozenset(
    {"Submitted", "Interrupted", "Stalled", "ProviderFault", "Error", "RepeatedFormatError"}
)


@dataclass
class ContinuityBrief:
    mission: str = ""
    done: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        def bullets(rows: list[str]) -> str:
            return "\n".join(f"- {r}" for r in rows) if rows else "- (none)"

        return (
            "## Continuity\n"
            f"- Mission: {self.mission or '(unknown)'}\n"
            f"- Done:\n{bullets(self.done)}\n"
            f"- Next:\n{bullets(self.next_steps)}\n"
            f"- Constraints:\n{bullets(self.constraints)}\n"
            f"- Paths:\n{bullets(self.paths)}\n"
            f"- Open todos:\n{bullets(self.todos)}\n"
        )


def _mission_from_messages(messages: list[dict], task: str) -> str:
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text") or p.get("content") or "") for p in content if isinstance(p, dict)
            )
        text = str(content).strip()
        if text and not text.startswith(COMPACTION_PREFIX):
            return text[:500]
    return (task or "")[:500]


def build_continuity_brief(
    *,
    messages: list[dict],
    todos: list[dict] | None = None,
    task: str = "",
) -> ContinuityBrief:
    open_todos = [
        str(t.get("content") or "").strip()
        for t in (todos or [])
        if str(t.get("status") or "") in {"pending", "in_progress"} and str(t.get("content") or "").strip()
    ]
    done: list[str] = []
    for m in messages[-20:]:
        if m.get("role") == "assistant":
            text = str(m.get("content") or "").strip()
            if text and not m.get("tool_calls"):
                done.append(text[:160])
                if len(done) >= 3:
                    break
    next_steps = list(open_todos[:5]) or ["Continue the unfinished task from continuity context."]
    return ContinuityBrief(
        mission=_mission_from_messages(messages, task),
        done=done or ["(see transcript)"],
        next_steps=next_steps,
        todos=open_todos,
    )


def has_unfinished_work(
    *,
    todos: list[dict] | None,
    exit_status: str,
    tool_call_count: int = 0,
) -> bool:
    status = (exit_status or "").strip()
    if status in {"Submitted", "Interrupted", "Stalled"}:
        return False
    for t in todos or []:
        if str(t.get("status") or "") in {"pending", "in_progress"}:
            return True
    return tool_call_count > 0 and status == "LimitsExceeded"


def should_budget_auto_continue(
    *,
    exit_status: str,
    continues_used: int,
    max_continues: int,
    todos: list[dict] | None,
    tool_call_count: int,
    inbox_queued: bool,
) -> bool:
    if inbox_queued:
        return False
    if continues_used >= max_continues:
        return False
    status = (exit_status or "").strip()
    if status != "LimitsExceeded":
        return False
    if status in _STOP_EXITS:
        return False
    return has_unfinished_work(todos=todos, exit_status=status, tool_call_count=tool_call_count)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_continuity.py -q`  
Expected: PASS

---

### Task 2: Persist + load continuity episodes

**Files:**
- Modify: `src/kite/memory/continuity.py` (add save/load helpers)
- Modify: `src/kite/memory/store.py` only if a thin wrapper is cleaner (prefer keeping logic in continuity.py using `MemoryStore.record_episode` / `episodes`)
- Test: `tests/test_continuity.py` (extend)

**Interfaces:**
- Consumes: `MemoryStore.record_episode`, `MemoryStore.episodes`, `MemoryStore.remember`
- Produces:
  - `save_continuity(*, store: MemoryStore, brief: ContinuityBrief, session_id: str, cwd: str) -> None`
  - `latest_continuity_markdown(store: MemoryStore, *, session_id: str = "", max_chars: int = 2_000) -> str`
  - `maybe_pin_project_fact(store: MemoryStore, brief: ContinuityBrief) -> bool` — at most one deduped project MEMORY bullet when paths/constraints present and project notes count < 40

- [ ] **Step 1: Write failing tests** (use `tmp_path` + `kite_home` fixture from conftest)

```python
def test_save_and_load_continuity(tmp_path, kite_home) -> None:
    from kite.memory.continuity import build_continuity_brief, latest_continuity_markdown, save_continuity
    from kite.memory.store import MemoryStore

    store = MemoryStore.open(tmp_path)
    brief = build_continuity_brief(
        messages=[{"role": "user", "content": "Fix login"}],
        todos=[{"status": "pending", "content": "patch handler"}],
        task="Fix login",
    )
    save_continuity(store=store, brief=brief, session_id="s1", cwd=str(tmp_path))
    md = latest_continuity_markdown(store, session_id="s1")
    assert "## Continuity" in md
    assert "Fix login" in md


def test_maybe_pin_project_fact_dedupes(tmp_path, kite_home) -> None:
    from kite.memory.continuity import ContinuityBrief, maybe_pin_project_fact
    from kite.memory.store import MemoryStore

    store = MemoryStore.open(tmp_path)
    brief = ContinuityBrief(mission="x", paths=["src/auth.py"], constraints=["no new deps"])
    assert maybe_pin_project_fact(store, brief) is True
    assert maybe_pin_project_fact(store, brief) is False  # dedupe
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_continuity.py::test_save_and_load_continuity tests/test_continuity.py::test_maybe_pin_project_fact_dedupes -q`  
Expected: FAIL (functions missing)

- [ ] **Step 3: Implement save/load/pin in `continuity.py`**

```python
def save_continuity(*, store, brief: ContinuityBrief, session_id: str, cwd: str) -> None:
    md = brief.to_markdown()
    store.record_episode(
        kind="continuity",
        summary=(brief.mission or "continuity")[:200],
        session_id=session_id,
        payload={"markdown": md, "todos": brief.todos, "paths": brief.paths},
        scope="project",
    )
    maybe_pin_project_fact(store, brief)


def latest_continuity_markdown(store, *, session_id: str = "", max_chars: int = 2_000) -> str:
    rows = store.episodes(limit=30, scope="project")
    for ep in rows:
        if ep.kind != "continuity":
            continue
        if session_id and ep.session_id and ep.session_id != session_id:
            continue
        payload = {}
        try:
            import json
            payload = json.loads(ep.payload or "{}")
        except Exception:
            payload = {}
        md = str(payload.get("markdown") or ep.summary or "")
        if md:
            return md[:max_chars]
    return ""


def maybe_pin_project_fact(store, brief: ContinuityBrief) -> bool:
    if not (brief.paths or brief.constraints):
        return False
    notes = store.notes(scope="project")
    if len(notes) >= 40:
        return False
    fact = "Continuity: " + "; ".join(
        (brief.paths[:3] + brief.constraints[:2])
    )
    fact = fact[:240]
    existing = {n.text.lower() for n in notes}
    if fact.lower() in existing:
        return False
    store.remember(fact, scope="project")
    return True
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_continuity.py -q`

---

### Task 3: Config — interactive floors + compact ratio 0.75

**Files:**
- Modify: `src/kite/data/configs/default.toml` (`compaction_ratio = 0.75`; add interactive knobs under `[agent]`)
- Modify: `src/kite/config/runtime.py` (fields + `_from_dict`)
- Modify: `src/kite/config/user.py` (optional user overrides + package-default detection helper)
- Create: `src/kite/config/interactive_budget.py` (pure resolve function — keeps UserConfig small)
- Test: `tests/test_interactive_budget.py`
- Also update defaults in: `src/kite/context/window.py` (`DEFAULT_COMPACT_RATIO = 0.75`), `src/kite/agent/compaction.py`, `src/kite/memory/compaction_ops.py`, `src/kite/agent/loop.py` default arg — keep consistent

**Interfaces:**
- Produces: `resolve_interactive_limits(*, interactive: bool, user_step: int, user_cost: float, runtime_step: int, runtime_cost: float, interactive_step: int = 80, interactive_cost: float = 10.0, package_step: int = 40, package_cost: float = 5.0) -> tuple[int, float]`

Logic:
- If not interactive → return `(runtime_step, runtime_cost)` (caller already applied options)
- If `user_step != package_step` → use `runtime_step` as-is for steps (user/runtime already merged); same for cost when `user_cost != package_cost`
- Else apply `max(runtime_step, interactive_step)` / `max(runtime_cost, interactive_cost)`

Clarify merge order in tests: when user left defaults (40/5), interactive chat gets 80/10; when user set 20/1.0, keep 20/1.0.

- [ ] **Step 1: Failing tests for resolve helper + compact default**

```python
# tests/test_interactive_budget.py
from kite.config.interactive_budget import resolve_interactive_limits
from kite.context.window import DEFAULT_COMPACT_RATIO


def test_interactive_floors_on_package_defaults() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=True,
        user_step=40,
        user_cost=5.0,
        runtime_step=40,
        runtime_cost=5.0,
    )
    assert steps == 80
    assert cost == 10.0


def test_honor_explicit_lower_user_caps() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=True,
        user_step=20,
        user_cost=1.0,
        runtime_step=20,
        runtime_cost=1.0,
    )
    assert steps == 20
    assert cost == 1.0


def test_non_interactive_unchanged() -> None:
    steps, cost = resolve_interactive_limits(
        interactive=False,
        user_step=40,
        user_cost=5.0,
        runtime_step=40,
        runtime_cost=5.0,
    )
    assert steps == 40
    assert cost == 5.0


def test_default_compact_ratio_is_075() -> None:
    assert DEFAULT_COMPACT_RATIO == 0.75
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement helper + bump defaults in toml/runtime/window/compaction modules to 0.75; add to `AgentRuntimeConfig`:**

```python
interactive_step_limit: int = 80
interactive_cost_limit: float = 10.0
max_budget_continues: int = 2
```

Wire `_from_dict` reading `agent.interactive_step_limit`, `agent.interactive_cost_limit`, `agent.max_budget_continues`.

- [ ] **Step 4: Run tests — PASS**

---

### Task 4: Runtime applies interactive budgets + injects continuity

**Files:**
- Modify: `src/kite/agent/runtime.py` (after computing `step_limit`/`cost_limit`, if `self.options.interactive`, call `resolve_interactive_limits`; append continuity markdown into `memory_text` or `extra_sections`)
- Modify: `src/kite/agent/harness.py` only if needed to pass through (Harness already sets `interactive=True` from ChatSession)
- Test: `tests/test_interactive_budget_runtime.py` (unit-test the limit resolution path with a thin helper export OR test `resolve_interactive_limits` integration already covered — add a focused test that runtime options + interactive floors are applied via a small extracted function `effective_agent_limits(...)` if cleaner)

Prefer extracting in `interactive_budget.py`:

```python
def effective_agent_limits(
    *,
    interactive: bool,
    options_step: int | None,
    options_cost: float | None,
    runtime_step: int,
    runtime_cost: float,
    user_step: int,
    user_cost: float,
    interactive_step: int,
    interactive_cost: float,
    long_task: bool,
) -> tuple[int, float]:
    step = options_step if options_step is not None else runtime_step
    cost = options_cost if options_cost is not None else runtime_cost
    if long_task:
        if options_step is None:
            step = max(step, 120)
        if options_cost is None:
            cost = max(cost, 25.0)
    if interactive and options_step is None and options_cost is None:
        step, cost = resolve_interactive_limits(
            interactive=True,
            user_step=user_step,
            user_cost=user_cost,
            runtime_step=step,
            runtime_cost=cost,
            interactive_step=interactive_step,
            interactive_cost=interactive_cost,
        )
    elif interactive:
        # Still apply floors per-dimension when that dimension was not explicitly overridden
        ...
    return step, cost
```

Keep the function’s exact behavior covered by tests; call it from `AgentRuntime.run` replacing the current long_task block.

For continuity inject in `prepare()` / `run()` after `memory_text = ...`:

```python
from kite.memory.continuity import latest_continuity_markdown
cont = latest_continuity_markdown(mem, session_id=self.options.session_id or "")
if cont:
    memory_text = (memory_text + "\n\n" + cont).strip() if memory_text else cont
```

- [ ] **Step 1: Tests for `effective_agent_limits` long_task + interactive floors**
- [ ] **Step 2: FAIL**
- [ ] **Step 3: Implement + wire runtime**
- [ ] **Step 4: PASS** — `pytest tests/test_interactive_budget.py tests/test_continuity.py -q`

---

### Task 5: Record continuity after successful compaction

**Files:**
- Modify: `src/kite/agent/loop.py` `_maybe_compact` — after `result.compacted`, build+save continuity via memory store if available
- Or modify: `src/kite/agent/compaction.py` / `memory/compaction_ops.py` to accept optional `on_compacted` callback — prefer loop hook to avoid widening compaction_ops signature too much
- Test: `tests/test_compact_continuity.py` with a stub agent or direct call to a small helper `record_continuity_after_compact(...)`

```python
def record_continuity_after_compact(
    *,
    store,
    messages,
    todos,
    session_id: str,
    cwd: str,
    task: str = "",
) -> str:
    brief = build_continuity_brief(messages=messages, todos=todos, task=task)
    save_continuity(store=store, brief=brief, session_id=session_id, cwd=cwd)
    return brief.to_markdown()
```

DefaultAgent may not have MemoryStore today — pass via todos owner or open `MemoryStore.open(cwd)` from `session`/env cwd. Use `Path(self.env.cwd)` or session meta cwd if present; fall back to `"."`.

- [ ] **Step 1: Failing test that helper saves episode**
- [ ] **Step 2: FAIL**
- [ ] **Step 3: Add helper + call from `_maybe_compact` when compacted**
- [ ] **Step 4: PASS**

---

### Task 6: REPL capped auto-continue loop

**Files:**
- Modify: `src/kite/ui/repl.py` `_run_task`
- Test: `tests/test_repl_budget_continue.py` (mock harness/`execute_harness_task` to return LimitsExceeded then Submitted)

**Behavior:**

After first worker completes with result:

```python
continues = 0
max_c = UserConfig / runtime max_budget_continues (default 2)

while should_budget_auto_continue(...):
    if self._inbox:
        break
    continues += 1
    # build+save continuity from session messages if possible
    brief_md = ...
    self.console.print(f"[kite.muted]budget continue {continues}/{max_c} — resuming…[/]")
    self.state.set_running(label=f"budget continue {continues}/{max_c}", kind="turn")
    # re-run harness with follow_up = brief_md + "Continue the unfinished work."
    # keep composer pinned: either nest another busy composer wait OR run worker while existing composer loop still active

```

**Important:** Current `_run_task` starts one worker then blocks in `read_repl_busy_composer` until `done`. Auto-continue must happen **before** clearing busy / leaving the function, while composer can stay up:

Preferred structure:

1. Extract inner `run_once(follow_up: str | None) -> dict` that starts worker + waits on `done` (composer already running once for the whole chain).
2. Or: after first `done.wait()`, if should continue, start another worker without exiting busy mode, and keep calling into a short wait loop (composer still active if we don't return).

Simplest reliable approach matching current code:

- Keep `read_repl_busy_composer` for the whole chain with `should_continue=lambda: not chain_done.is_set()`.
- Worker function runs a loop: execute task → if should auto-continue, emit muted event / print via console through patch, save continuity, execute follow-up, else break; set `chain_done`.

Because console prints from worker thread need patch_stdout (already active on main), prefer signaling main thread via a queue of UI messages, or print from main between continues by restructuring so continues run on main thread between composer polls.

**Recommended structure (main-thread continues):**

```python
# pseudo in _run_task
self._busy = True
self.state.busy = True
self.display._spin(False)
session = self._ensure_prompt()
continues = 0
follow = task if resume else None
current_task = task
chain_active = True

def spawn(follow_up: str | None):
    # start thread for one harness run; return done Event + box

done, box = spawn(follow if resume else None)
# start busy composer once with should_continue=lambda: chain_active or not done.is_set()
# AFTER done.wait() on main:
while True:
    done.wait()
    result = box.get("result") or {}
    if should_budget_auto_continue(...) and not self._inbox:
        continues += 1
        # save continuity; set follow-up text
        self.console.print(...)
        done, box = spawn(follow_up=continue_prompt)
        continue
    chain_active = False
    break
```

Composer `should_continue` must stay true across respawns until chain ends — use a flag `self._turn_chain_active`.

- [ ] **Step 1: Write failing unit test for a pure orchestrator helper** to avoid full TTY:

Create `src/kite/ui/budget_continue.py`:

```python
def next_budget_action(
    *,
    exit_status: str,
    continues_used: int,
    max_continues: int,
    todos: list[dict] | None,
    tool_call_count: int,
    inbox_queued: bool,
) -> str:
    """Return 'continue' | 'stop'."""
    if should_budget_auto_continue(...):
        return "continue"
    return "stop"
```

Test that; then integrate into `_run_task` with a focused test mocking `execute_harness_task` sequence `[LimitsExceeded, Submitted]` and asserting two calls when todos unfinished.

- [ ] **Step 2–4: TDD the helper, then wire `_run_task`, assert call count with mocks**

---

### Task 7: Docs + regression suite

**Files:**
- Modify: `docs/cli-ux.md` — budget pause section: interactive floors, auto-continue ≤2, continuity memory
- Modify: `docs/superpowers/specs/2026-09-06-adaptive-budget-smart-memory-design.md` status → `implemented` when done (optional)
- Run: `pytest tests/test_continuity.py tests/test_interactive_budget.py tests/test_repl_budget_continue.py tests/test_limits_exceeded.py tests/test_ui_busy.py tests/test_composer.py -q`

- [ ] **Step 1: Update cli-ux.md** with adaptive budget + continuity bullets
- [ ] **Step 2: Run full related pytest suite — all PASS**
- [ ] **Step 3: Manual smoke (optional):** `kite` → long task → observe `budget continue 1/2` if limits hit with open todos

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Interactive ~80/$10 on defaults | 3, 4 |
| Honor lower user caps | 3 |
| Auto-continue ≤2 on LimitsExceeded + unfinished | 1, 6 |
| Inbox wins over auto-continue | 1, 6 |
| No continue on Submitted/Interrupted/Stalled/ProviderFault | 1 |
| Continuity brief build/store/inject | 1, 2, 4, 5 |
| Compact ratio 0.75; checkpoint 0.72 | 3, 5 |
| Non-interactive unchanged | 3, 4 |
| UX muted `budget continue N/2` | 6 |
| Docs | 7 |

## Placeholder / consistency scan

- Function names aligned: `build_continuity_brief`, `save_continuity`, `latest_continuity_markdown`, `should_budget_auto_continue`, `resolve_interactive_limits`, `effective_agent_limits`
- No TBD steps remaining
