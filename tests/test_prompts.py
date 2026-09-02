"""Don't wrap a greeting as a coding task."""

from __future__ import annotations

from kite.agent.loop import DefaultAgent
from kite.config import load_runtime_config
from kite.prompts import (
    assemble_instance_prompt,
    assemble_system_prompt,
    discover_system_prompt_files,
    load_prompt_template,
)


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


def test_instance_prompt_is_task_only() -> None:
    cfg = load_runtime_config()
    text = assemble_instance_prompt(config=cfg, task="hi")
    assert text.strip() == "hi"


def test_system_prompt_matches_effort_on_greetings() -> None:
    system = load_prompt_template("system")
    assert "no tools" in system.lower() or "Don't open the repo" in system or "Greetings" in system
    assert "hi" in system.lower() or "Greetings" in system
    assert 'Asking the user "hi"' not in system


def test_system_prompt_has_working_loop() -> None:
    system = load_prompt_template("system")
    assert "## Working loop" in system
    assert "Orient" in system
    assert "Verify" in system
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in system


def test_build_mode_does_not_force_checklist_on_chat() -> None:
    build = load_prompt_template("mode_build")
    assert "Don't start a checklist" in build


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
    assert "## Session time" in text
    assert "UTC:" in text
    assert "## Effort" in text
    assert "Greetings" in text or "short questions" in text


def test_system_prompt_mentions_context7_and_websearch() -> None:
    system = load_prompt_template("system")
    assert "context7_resolve" in system
    assert "websearch" in system
    assert "no other built-in mcp servers" in system.lower()


def test_discover_system_and_append(tmp_path, monkeypatch) -> None:
    home = tmp_path / "kite_home"
    home.mkdir()
    monkeypatch.setenv("KITE_HOME", str(home))
    (home / "SYSTEM.md").write_text("GLOBAL BASE", encoding="utf-8")
    (home / "APPEND_SYSTEM.md").write_text("GLOBAL APPEND", encoding="utf-8")

    project = tmp_path / "proj"
    (project / ".kite").mkdir(parents=True)
    (project / ".kite" / "SYSTEM.md").write_text("PROJECT BASE", encoding="utf-8")
    (project / ".kite" / "APPEND_SYSTEM.md").write_text("PROJECT APPEND", encoding="utf-8")

    override, append = discover_system_prompt_files(project)
    assert override == "PROJECT BASE"
    assert append == "PROJECT APPEND"

    other = tmp_path / "other"
    other.mkdir()
    override, append = discover_system_prompt_files(other)
    assert override == "GLOBAL BASE"
    assert append == "GLOBAL APPEND"


def test_assemble_uses_discovered_system_files(tmp_path, monkeypatch) -> None:
    home = tmp_path / "kite_home"
    home.mkdir()
    monkeypatch.setenv("KITE_HOME", str(home))
    project = tmp_path / "proj"
    (project / ".kite").mkdir(parents=True)
    (project / ".kite" / "SYSTEM.md").write_text("CUSTOM BASE\n\n## Effort\nok", encoding="utf-8")
    (project / ".kite" / "APPEND_SYSTEM.md").write_text("## Extra\nbe brief", encoding="utf-8")

    cfg = load_runtime_config()
    text = assemble_system_prompt(config=cfg, cwd=project)
    assert "CUSTOM BASE" in text
    assert "## Extra" in text
    assert "be brief" in text
    # Bundled prompt should not appear when SYSTEM.md replaces it
    assert "You are Kite — a careful coding agent" not in text
