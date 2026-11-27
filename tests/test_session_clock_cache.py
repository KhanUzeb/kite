"""Offline evidence about the session clock and prompt-cache prefix stability.

No provider calls: these tests observe the exact message list Kite would render.
"""

from __future__ import annotations

from types import SimpleNamespace

from kite.agent.hooks import HookBus
from kite.agent.loop import DefaultAgent
from kite.context import clock as clock_mod
from kite.models.cache import apply_cache_breakpoints


class _StubModel:
    resolved = SimpleNamespace(provider="stub", model="stub")

    def __init__(self) -> None:
        self.seen: list[list[dict]] = []
        self.calls = 0

    def format_message(self, role, content="", extra=None, **kwargs):
        msg = {"role": role, "content": content, **kwargs}
        if extra is not None:
            msg["extra"] = extra
        return msg

    def query(self, messages):
        self.calls += 1
        self.seen.append(list(messages))
        return self.format_message(
            "assistant",
            "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nDone.",
        )

    def format_observation_messages(self, message, outputs, template_vars=None):
        return []


class _StubEnv:
    def execute(self, action, cwd=""):
        return {"ok": True, "output": ""}


def _run(model: _StubModel, *, resume_messages=None, project_context: str) -> None:
    agent = DefaultAgent(
        model,
        _StubEnv(),
        system_prompt="stable instructions",
        instance_prompt="{task}",
        project_context=project_context,
        resume_messages=resume_messages,
        context_window=200_000,
        step_limit=2,
        hooks=HookBus(),
        on_event=lambda event: None,
    )
    result = agent.run("task")
    assert result.get("exit_status") == "Submitted"


def test_session_clock_has_minute_granularity(monkeypatch) -> None:
    class FakeDateTime:
        text = "2026-11-27 12:00 UTC"

        def __init__(self, text: str) -> None:
            self.text = text

        @classmethod
        def now(cls, tz=None):
            return cls(cls.text)

        def astimezone(self):
            return self

        def strftime(self, fmt: str) -> str:
            return self.text

        def tzname(self):
            return "UTC"

    monkeypatch.setattr(clock_mod, "datetime", FakeDateTime)
    first = clock_mod.session_time_section()

    FakeDateTime.text = "2026-11-27 12:01 UTC"
    second = clock_mod.session_time_section()

    assert first != second
    assert "UTC" in first


def test_resumed_turn_keeps_original_setup_message(monkeypatch) -> None:
    """A fresh clock on a later turn must not rewrite the cached setup prefix."""
    import kite.prompts as prompts_mod
    from kite.config import load_runtime_config

    monkeypatch.setattr(prompts_mod, "session_time_section", lambda: "## Session time\n- UTC: 12:00")

    _, setup = prompts_mod.split_system_and_setup(config=load_runtime_config())
    first_setup = f"# Setup (reference — not the task)\n{setup}"

    first_model = _StubModel()
    _run(first_model, project_context=first_setup)
    turn1 = first_model.seen[0]

    # Later turn: runtime re-renders setup with a newer clock, but the harness
    # resumes from the stored session messages.
    monkeypatch.setattr(prompts_mod, "session_time_section", lambda: "## Session time\n- UTC: 12:07")
    _, later_setup = prompts_mod.split_system_and_setup(config=load_runtime_config())
    changed_setup = f"# Setup (reference — not the task)\n{later_setup}"
    assert changed_setup != first_setup

    second_model = _StubModel()
    _run(second_model, resume_messages=turn1, project_context=changed_setup)
    turn2 = second_model.seen[0]

    setup1 = next(m for m in turn1 if m.get("extra", {}).get("setup"))
    setup2 = next(m for m in turn2 if m.get("extra", {}).get("setup"))
    assert setup2["content"] == setup1["content"]
    assert "12:00" in setup2["content"]
    assert "12:07" not in setup2["content"]


def test_rendered_prefix_is_stable_across_resumed_turns() -> None:
    model = _StubModel()
    _run(model, project_context="# Setup (reference — not the task)\n- cwd: /r")
    turn1 = model.seen[0]

    model2 = _StubModel()
    _run(model2, resume_messages=turn1, project_context="# Setup (reference — not the task)\n- cwd: /other")
    turn2 = model2.seen[0]

    wired1 = apply_cache_breakpoints(turn1, provider="anthropic")
    wired2 = apply_cache_breakpoints(turn2, provider="anthropic")
    assert wired2[: len(wired1)] == wired1
