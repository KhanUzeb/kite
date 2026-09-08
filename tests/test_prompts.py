"""Don't wrap a greeting as a coding task."""

from __future__ import annotations

from kite.agent.loop import DefaultAgent
from kite.config import load_runtime_config
from kite.prompts import assemble_system_prompt, discover_system_prompt_files, load_prompt_template


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


def test_oneshot_still_applies_instance_template() -> None:
    agent = DefaultAgent(_StubModel(), _StubEnv(), instance_prompt="TASK:{task}", interactive=False)
    assert agent._user_turn_text("hi", follow="hi", kwargs={}) == "TASK:hi"


def test_assemble_system_includes_effort_section() -> None:
    cfg = load_runtime_config()
    text = assemble_system_prompt(config=cfg)
    assert "## Effort" in text
    assert "Greetings" in text or "short questions" in text


def test_assemble_system_includes_harness_and_credentials_guidance() -> None:
    cfg = load_runtime_config()
    text = assemble_system_prompt(config=cfg)
    assert "## Credentials & secrets" in text
    assert "## Harness limits & workarounds" in text
    assert "## Skills (trust & supply chain)" in text
    assert "untrusted" in text
    assert "SSRF" in text or "localhost" in text
    assert "## User attachments" in text


def test_discover_system_and_append(tmp_path, monkeypatch) -> None:
    home = tmp_path / "kite_home"
    home.mkdir()
    monkeypatch.setenv("KITE_HOME", str(home))
    (home / "SYSTEM.md").write_text("GLOBAL BASE", encoding="utf-8")
    project = tmp_path / "proj"
    (project / ".kite").mkdir(parents=True)
    (project / ".kite" / "SYSTEM.md").write_text("PROJECT BASE", encoding="utf-8")
    override, append = discover_system_prompt_files(project)
    assert override == "PROJECT BASE"
    assert load_prompt_template("system")
