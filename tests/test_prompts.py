"""Don't wrap a greeting as a coding task."""

from __future__ import annotations

from kite.agent.loop import DefaultAgent
from kite.config import load_runtime_config
from kite.prompts import assemble_instance_prompt, assemble_system_prompt, load_prompt_template


class _StubModel:
    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def query(self, messages: list[dict]) -> dict:
        return {"role": "assistant", "content": "hello", "extra": {"actions": [], "cost": 0.0}}

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return [{"role": "tool", "content": str(outputs)}]


class _StubEnv:
    def execute(self, action: dict, cwd: str = "") -> dict:
        return {"ok": True, "output": ""}


def test_instance_prompt_wraps_task_without_legacy_boilerplate() -> None:
    cfg = load_runtime_config()
    text = assemble_instance_prompt(config=cfg, task="hi")
    assert text.startswith("hi")
    assert "Please solve this task" not in text
    assert "Inspect before editing" not in text
    assert "structured summary" in text


def test_system_prompt_matches_effort_on_greetings() -> None:
    system = load_prompt_template("system")
    assert "Greetings and short Q&A" in system
    assert "numbered action list" in system
    assert 'Asking the user "hi"' not in system


def test_build_mode_does_not_force_checklist_on_chat() -> None:
    build = load_prompt_template("mode_build")
    assert "reply in text for chat" in build


def test_interactive_hi_sends_raw_user_text() -> None:
    agent = DefaultAgent(
        _StubModel(),
        _StubEnv(),
        instance_prompt="Please solve this task:\n\n{task}\nInspect before editing.",
        interactive=True,
    )
    text = agent._user_turn_text("hi", follow="hi", kwargs={})
    assert text == "hi"
    assert "Please solve this task" not in text
    assert "Inspect before editing" not in text


def test_oneshot_still_applies_instance_template() -> None:
    agent = DefaultAgent(
        _StubModel(),
        _StubEnv(),
        instance_prompt="TASK:{task}",
        interactive=False,
    )
    text = agent._user_turn_text("hi", follow="hi", kwargs={})
    assert text == "TASK:hi"


def test_assemble_system_includes_effort_section() -> None:
    cfg = load_runtime_config()
    text = assemble_system_prompt(config=cfg)
    assert "## Effort" in text
    assert "numbered action list" in text
