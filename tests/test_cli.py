"""CLI apply, slash help, chat/resume flags, headless tasks."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kite.cli.apply_cmd import _path_inside_workspace, apply_unified_diff
from kite.cli.slash import CommandIndex, help_text
from kite.tasks import (
    HeadlessTask,
    load_tasks_text,
    parse_task_line,
    run_headless_batch,
    run_headless_task,
)
from kite.ui.commands import LEGACY_ALIASES, parse_slash
from kite.ui.pick import numbered_pick
from kite.ui.repl import ChatSession


def test_apply_diff_stays_inside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "root2"
    sibling.mkdir()
    assert not _path_inside_workspace(sibling, root)
    target = tmp_path / "a.txt"
    target.write_text("hello\n", encoding="utf-8")
    result = apply_unified_diff("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-hello\n+world\n", cwd=str(tmp_path))
    assert result["count"] == 1 and target.read_text(encoding="utf-8") == "world\n"


def test_typed_picker_selection_filter_paging_and_refresh(monkeypatch) -> None:
    console = MagicMock()
    console.input.return_value = "2"
    assert numbered_pick(console, [("a", "alpha"), ("b", "beta")], current="a", title="t", noun="model") == "b"
    console.input.return_value = ""
    assert numbered_pick(console, [("a", "alpha")], current=None, title="t", noun="item") is None
    console.input.return_value = "b"
    assert numbered_pick(console, [("a", "alpha"), ("b", "beta")], title="t", noun="model") == "b"
    console.input.side_effect = ["gpt", "2"]
    assert numbered_pick(
        console,
        [("gpt-4", "gpt-4"), ("gpt-4o", "gpt-4o"), ("claude", "claude")],
        current=None,
        title="t",
        noun="model",
    ) == "gpt-4o"
    items = [(str(i), f"m{i}") for i in range(1, 6)]
    console.input.side_effect = ["+", "1"]
    assert numbered_pick(console, items, current=None, title="t", noun="model", show=2) == "3"
    from kite.ui.pick import REFRESH_PICK, can_scroll_pick

    console.input.side_effect = None
    console.input.return_value = "r"
    assert numbered_pick(console, [("a", "a")], current=None, title="t", noun="model", refreshable=True) == REFRESH_PICK
    monkeypatch.setenv("KITE_TYPED_PICK", "1")
    assert can_scroll_pick() is False


def test_posix_picker_keys_and_mouse_coordinates() -> None:
    from kite.ui.pick import _posix_key, _posix_mouse, view_index_from_mouse

    assert _posix_key("\x1b[A") == "up"
    assert _posix_key("\x1b[B") == "down"
    assert _posix_key("\x1bOA") == "up"
    assert _posix_key("\x1bOB") == "down"
    assert _posix_key("\x1b[1;5A") == "up"
    assert _posix_key("\x1b") == "esc"

    assert view_index_from_mouse(mouse_y=12, item_y0=10, n_view=5) == 2
    assert view_index_from_mouse(mouse_y=9, item_y0=10, n_view=5) is None
    drawn = {"item_y0": 10, "n_view": 4}
    assert _posix_mouse("\x1b[<32;4;13M", drawn) == "goto:2"
    assert _posix_mouse("\x1b[<0;4;12m", drawn) == "pick:1"
    assert _posix_mouse("\x1b[<64;4;12M", drawn) == "up"


def test_picker_filter_never_absorbs_escape_fragments() -> None:
    """A PTY relay can split one control sequence across reads.

    The tail (``[B``, ``<35;22;19M``) is all printable, so it used to land in
    the type-to-filter buffer: every row stopped matching, the heading read
    "0 matches" plus raw bytes, and the panel repainted forever.
    """
    from kite.ui.pick import _consume_event, _filter_char

    for ch in "[];<>~":
        assert not _filter_char(ch), ch
    # Ordinary filter characters must still work, including letters that appear
    # inside control sequences (M, O) and punctuation like _ and -.
    for ch in "abcdefghijklmnopqrstuvwxyzABCOPM0123456789.-_/*+ '\"{}#":
        assert _filter_char(ch), ch

    # A whole SGR mouse report is consumed as one sequence, not eight chars.
    ev, rest, more = _consume_event("\x1b[<35;22;19Mabc", {})
    assert more is False and rest == "abc"
    assert ev is None or ev.startswith(("goto:", "pick:"))

    # Cursor keys still decode.
    assert _consume_event("\x1b[B", {})[0] == "down"
    assert _consume_event("\x1b[A", {})[0] == "up"


def test_win_click_release_selects() -> None:
    """Windows press highlights, release confirms — same as the POSIX path."""
    from types import SimpleNamespace

    from kite.ui.pick import _WinEvents

    picker = _WinEvents.__new__(_WinEvents)
    picker._drawn = {"item_y0": 10, "n_view": 4}
    picker._down = False

    def _click(*, buttons: int, y: int, flags: int = 0):
        mouse = SimpleNamespace(
            EventFlags=flags,
            ButtonState=buttons,
            MousePosition=SimpleNamespace(Y=y),
        )
        return picker._mouse(mouse)

    assert _click(buttons=0x1, y=11) == "goto:1"
    assert _click(buttons=0x0, y=11) == "pick:1"
    assert _click(buttons=0x1, y=11) == "goto:1"
    assert _click(buttons=0x0, y=99) == "enter"
    assert _click(buttons=0x0, y=11) is None  # release without press: no-op


def test_picker_terminal_type_and_relay_guards(monkeypatch) -> None:
    """A Windows relay is a PTY: never drive it with msvcrt, never ask for mouse."""
    import sys

    from kite.ui import pick

    monkeypatch.setattr(pick, "_pick_debug", lambda *_a, **_k: None)
    seen: list[str] = []

    class _FakeReader:
        def __init__(self, drawn, tag):
            seen.append(tag)
            self._drawn = drawn

    monkeypatch.setattr(pick, "_PosixEvents", lambda d: _FakeReader(d, "posix"))
    monkeypatch.setattr(pick, "_WinPtyEvents", lambda d: _FakeReader(d, "pty"))
    monkeypatch.setattr(pick, "_WinEvents", lambda d: _FakeReader(d, "console"))
    monkeypatch.setattr(pick, "_WinKeyOnly", lambda d: _FakeReader(d, "keyonly"))

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(pick, "native_console", lambda: False)
    pick._event_reader({})
    assert seen[-1] == "pty", "a PTY relay must not get the console reader"
    monkeypatch.setattr(pick, "native_console", lambda: True)
    pick._event_reader({})
    assert seen[-1] == "console"

    monkeypatch.setattr(sys, "platform", "linux")
    pick._event_reader({})
    assert seen[-1] == "posix"

    # Relay sessions must not receive SGR mouse-enable bytes (they echo junk).
    monkeypatch.setenv("ORCA_RELAY", "1")
    assert pick.mouse_supported() is False
    monkeypatch.delenv("ORCA_RELAY")
    assert pick.mouse_supported() is True

    # Our own cursor-position probe is parsed, never leaked into the filter.
    ev, rest, need_more = pick._consume_event("\x1b[12;40Rabc", {})
    assert ev == "__cpr__:12;40" and rest == "abc" and need_more is False


def test_picker_multi_select_typed_fallback() -> None:
    console = MagicMock()
    console.input.side_effect = ["2,1"]
    picked = numbered_pick(
        console,
        [("red", "red"), ("blue", "blue"), ("green", "green")],
        title="Color",
        noun="option",
        multiple=True,
    )
    assert picked == ["red", "blue"], "list order, not typed order"

    console.input.side_effect = [""]
    assert numbered_pick(console, [("a", "a")], title="t", noun="option", multiple=True) == []


def test_render_pick_list_cursor_checkbox_and_details() -> None:
    from kite.ui.credentials import render_pick_list

    panel = render_pick_list(
        [("red", "red"), ("blue", "blue")],
        title="Color",
        cursor=1,
        checked={"red"},
        details={"blue": "cool tones"},
        hint="↑/↓ move",
    )
    text = panel.plain
    assert "▸" in text and "▸" in text.split("blue")[0]
    assert "cool tones" in text, "multi-line rows need the description rendered"
    assert text.rstrip().endswith("↑/↓ move"), "explicit hint replaces the default footer"


def test_theme_font_subcommands(kite_home, monkeypatch) -> None:
    from kite.cli.run import cmd_font, cmd_theme
    from kite.config import UserConfig
    from kite.ui import theme

    monkeypatch.setattr(theme, "_prefs", theme.UiPrefs())
    monkeypatch.setattr(theme, "_loaded", True)
    assert cmd_theme(argparse.Namespace(name="nope", list=False)) == 2
    assert cmd_theme(argparse.Namespace(name="dark", list=False)) == 0
    assert theme.theme_label() == "dark"
    assert UserConfig.load().theme == "dark"
    assert cmd_font(argparse.Namespace(name="ascii", list=False)) == 0
    assert theme.current_font() == "ascii"
    assert UserConfig.load().font == "ascii"
    assert cmd_font(argparse.Namespace(name="bogus", list=False)) == 2
    assert theme.current_font() == "ascii"


def test_variants_list_distinguishes_timeout_from_unsupported(kite_home, monkeypatch, capsys) -> None:
    from types import SimpleNamespace

    import kite.models.reasoning as reasoning
    from kite.cli import run

    # Advance the detection worker deterministically instead of leaving two
    # 30-second sleepers alive after two real half-second join timeouts.
    pending = True

    class DetectionWorker:
        def __init__(self, *, target, daemon, name):
            self.target = target

        def start(self):
            if not pending:
                self.target()

        def join(self, timeout=None):
            assert timeout == 0.01, "detection must use a bounded join"

        def is_alive(self):
            return pending

    monkeypatch.setattr("threading.Thread", DetectionWorker)
    monkeypatch.setattr(run, "_VARIANTS_DETECT_TIMEOUT_S", 0.01)
    monkeypatch.setattr(
        "kite.providers.resolve.resolve_model",
        lambda **_: SimpleNamespace(provider="groq", model="m", litellm_model="groq/m"),
    )
    monkeypatch.setattr(reasoning, "peek_reasoning", lambda *_a, **_k: None)
    monkeypatch.setattr(reasoning, "detect_reasoning", lambda *_a, **_k: SimpleNamespace(supported=False))
    args = argparse.Namespace(provider=None, model=None, level=None, list=True)
    assert run.cmd_variants(args) == 1
    assert "detection timed out" in capsys.readouterr().err

    pending = False
    assert run.cmd_variants(args) == 1
    output = capsys.readouterr().err
    assert "does not advertise thinking variants" in output
    assert "timed out" not in output


def test_slash_help_and_legacy_routing(workspace) -> None:
    assert parse_slash("/select groq").command == "select"
    assert parse_slash("/thinking").command == "thinking"
    assert parse_slash("/skill commit").command == "skill"
    assert parse_slash("/collapse").command == "collapse"
    assert "skill" not in LEGACY_ALIASES
    session = ChatSession.__new__(ChatSession)
    cmd, arg = session._apply_legacy_slash("model", "groq", "select")
    assert cmd == "model" and arg == "select groq"
    text = help_text(CommandIndex.load(workspace))
    assert "/plan" in text and "More: /help all" in text
    text_all = help_text(CommandIndex.load(workspace), all=True)
    assert "session" in text_all and "/select" in text_all
    from kite import __version__

    assert "kite_commands.md" in text_all and "CONTEXT.md" in text_all
    assert "architecture.md" in text_all and "SECURITY.md" in text_all
    assert f"docs/RELEASE-{__version__}.md" in text_all
    assert "kite-system-design" not in text and "docs/memory.md" not in text


def test_chat_rejects_missing_attachments_and_output_flags(monkeypatch, kite_home) -> None:
    from kite.cli.run import build_parser, main

    parser = build_parser()
    for flag in ("--headless", "--json", "--quiet", "--no-stream"):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["chat", flag])
        assert exc.value.code == 2
    monkeypatch.setattr("kite.ui.repl.ChatSession", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no start")))
    assert main(["chat", "--attach", "/definitely/missing"]) == 2


def test_resume_transcript_context_and_exit_status(monkeypatch, workspace, kite_home) -> None:
    from io import StringIO

    from rich.console import Console

    from kite.application.cli import ExitCode
    from kite.application.contracts import RunResult
    from kite.cli import run
    from kite.memory.session import Session, SessionMeta

    stored = Session(
        meta=SessionMeta(
            id="sess83", created_at=1.0, updated_at=2.0, cwd=str(workspace),
            provider="groq", model="x", task="t",
        ),
        messages=[
            {"role": "user", "content": "What is Kite?"},
            {"role": "assistant", "content": "A coding agent."},
            {
                "role": "exit",
                "content": "Submitted",
                "extra": {"exit_status": "Submitted", "submission": "done bullets"},
            },
        ],
    )
    monkeypatch.setattr("kite.memory.session.load_session", lambda *_a, **_k: stored)
    buf = StringIO()
    monkeypatch.setattr(run, "_console", lambda: Console(file=buf, force_terminal=False, width=200))
    seen: dict = {}

    def fake_build(**kwargs):
        seen.update(kwargs)
        return MagicMock()

    harness = MagicMock(last_session=None)
    harness.teardown_jobs.return_value = 0
    monkeypatch.setattr("kite.agent.harness_build.build_harness_config", fake_build)
    monkeypatch.setattr("kite.agent.harness.Harness", lambda _config: harness)
    monkeypatch.setattr(
        "kite.application.cli.execute_harness_task",
        lambda *_a, **_k: RunResult(
            status="completed", stop_reason="submitted", final_message="ok",
            legacy={"exit_status": "Submitted", "submission": "ok"},
        ),
    )
    parser = run.build_parser()
    assert run.cmd_resume(parser.parse_args(["resume", "sess83", "--json"])) == 2
    args = parser.parse_args(["resume", "sess83", "continue"])
    args.cwd = str(workspace)
    assert run.cmd_resume(args) == 0
    transcript = buf.getvalue()
    assert transcript.index("What is Kite?") < transcript.index("A coding agent.") < transcript.index("done bullets")
    assert seen["resume"] is True
    assert seen["session_id"] == "sess83"
    assert seen["follow_up"] == "continue"

    for reason, code in (
        ("interrupted", ExitCode.CANCELLED),
        ("approval_denied", ExitCode.APPROVAL_DENIED),
        ("verification_failed", ExitCode.VERIFICATION_FAILED),
    ):
        monkeypatch.setattr(
            "kite.application.cli.execute_harness_task",
            lambda *_a, _reason=reason, **_k: RunResult(status="failed", stop_reason=_reason),
        )
        assert run.cmd_resume(args) == code
    monkeypatch.setattr(
        "kite.application.cli.execute_harness_task",
        lambda *_a, **_k: RunResult(status="completed", stop_reason="submitted", legacy={"exit_status": "Submitted"}),
    )
    harness.teardown_jobs.return_value = 1
    assert run.cmd_resume(args) == 1, "leftover jobs must not report a successful resume"
    harness.teardown_jobs.return_value = 0
    monkeypatch.setattr(run, "_wire_display", lambda *_a: (_ for _ in ()).throw(ValueError("bad runtime config")))
    assert run.cmd_resume(args) == 1, "setup errors must use the normal CLI error result"


def test_cli_help_documents_accepted_flags_without_loading_credentials(monkeypatch, kite_home) -> None:
    import re

    from kite.cli.help_map import cli_help_brief, cli_help_text
    from kite.cli.run import build_parser, main

    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices
    assert "kite help all" in cli_help_brief()
    text = cli_help_text()
    assert "kite_commands.md" in text and "CONTEXT.md" in text
    assert "kite-system-design" not in text
    flags = set(re.findall(r"--[a-z0-9-]+", text.split("Flags on run:")[-1]))
    combined = "".join(commands[name].format_help() for name in ("run", "chat", "resume", "config"))
    assert [flag for flag in flags if flag not in combined] == []
    assert "maintainer" not in parser.format_help()
    monkeypatch.setattr("kite.providers.credentials.load_kite_env", lambda: (_ for _ in ()).throw(AssertionError("help must not read credentials")))
    for command in ("run", "models", "sessions", "setup"):
        with pytest.raises(SystemExit) as exc:
            main([command, "--help"])
        assert exc.value.code == 0


def test_resume_requires_session_without_prompt(monkeypatch, kite_home) -> None:
    from kite.cli.run import cmd_resume

    monkeypatch.setattr("kite.ui.pick.can_prompt", lambda: False)
    assert cmd_resume(argparse.Namespace(session=None)) == 2


def test_headless_tasks_parse_plain_text_and_json() -> None:
    task = parse_task_line("fix the tests", default_cwd="/tmp/ws")
    assert task and task.task == "fix the tests" and task.cwd == "/tmp/ws"
    json_task = parse_task_line('{"task": "scout auth", "label": "auth", "profile": "scout", "mode": "plan"}')
    assert json_task and json_task.label == "auth"
    tasks = load_tasks_text("# header\n\nrun tests\n\n{\"task\": \"lint\", \"label\": \"lint\"}\n", default_cwd=".")
    assert len(tasks) == 2
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_task_line("{not json}")


def test_headless_only_submitted_tasks_succeed(monkeypatch, workspace, kite_home) -> None:
    from kite.application.contracts import RunResult

    harness = MagicMock(last_session=None)
    harness.teardown_jobs.return_value = 0
    monkeypatch.setattr("kite.agent.harness_build.build_harness_config", lambda **_k: None)
    monkeypatch.setattr("kite.agent.harness.Harness", lambda _config: harness)

    def fake_execute(harness, task):  # noqa: ANN001
        return RunResult(status="failed", stop_reason="error", final_message="", legacy={"exit_status": "Stalled", "submission": "", "error": "Stalled"})

    monkeypatch.setattr("kite.application.cli.execute_harness_task", fake_execute)
    stalled = run_headless_task(HeadlessTask(task="do work", cwd=str(workspace)))
    assert stalled.ok is False and stalled.exit_status == "Stalled"

    def submitted(harness, task):  # noqa: ANN001
        return RunResult(status="completed", stop_reason="submitted", final_message="done", legacy={"exit_status": "Submitted", "submission": "done"})

    monkeypatch.setattr("kite.application.cli.execute_harness_task", submitted)
    ok = run_headless_task(HeadlessTask(task="do work", cwd=str(workspace)))
    assert ok.ok is True

    def fake_run(task: HeadlessTask, **kwargs):
        from kite.tasks import HeadlessTaskResult

        return HeadlessTaskResult(index=0, label=task.label, ok=False, exit_status="ProviderFault", session_id="s1")

    monkeypatch.setattr("kite.tasks.run_headless_task", fake_run)
    batch = run_headless_batch([HeadlessTask(task="one", label="a")], continue_on_error=True)
    assert batch.ok is False and batch.to_dict()["succeeded"] == 0


def test_implicit_prompt_routing() -> None:
    # Implicit prompt routing (Pi-style): bare words become chat/run.
    from kite.cli.run import rewrite_implicit_task

    assert rewrite_implicit_task(["run", "x"]) == ["run", "x"]
    assert rewrite_implicit_task(["--help"]) == ["--help"]
    rewritten = rewrite_implicit_task(["fix", "the", "tests"])
    assert rewritten[0] in {"chat", "run"}
    assert rewritten[1:] == ["fix", "the", "tests"]
    assert rewrite_implicit_task(["fix", "--headless"])[0] == "run"
    # Self-manage commands are real subcommands, never chat prompts.
    assert rewrite_implicit_task(["update"]) == ["update"]
    assert rewrite_implicit_task(["uninstall", "-y"]) == ["uninstall", "-y"]
    assert rewrite_implicit_task(["fix", "--print"])[0] == "run"


def test_update_and_uninstall_missing_manager(monkeypatch, kite_home, capsys) -> None:
    # update --check is read-only: version + mode, no uv calls.
    from kite import __version__
    from kite.cli.run import main

    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert main(["update", "--check"]) == 0
    assert __version__ in capsys.readouterr().err

    # update on a managed install runs `uv tool upgrade kite` (mocked, headless-safe).
    # (Windows instead hands off to a detached helper — see next test.)
    monkeypatch.setattr("kite.cli.self_manage._use_detached_handoff", lambda: False)
    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = f"kite v{__version__}\n- kite\n"
        stderr = ""

    monkeypatch.setattr("shutil.which", lambda name: f"C:\\bin\\{name}.exe")
    monkeypatch.setattr(
        "kite.cli.self_manage.subprocess.run",
        lambda cmd, **_k: calls.append(list(cmd)) or _Proc(),
    )
    assert main(["update"]) == 0
    assert any(cmd[:3] == ["C:\\bin\\uv.exe", "tool", "upgrade"] for cmd in calls)

    # uninstall without uv on PATH is guidance, not a crash.
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert main(["uninstall", "-y"]) == 2

    # --print with no prompt and no piped stdin explains usage (exit 2, no harness).
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert main(["--print"]) == 2


def test_windows_update_handoff_script(monkeypatch, tmp_path) -> None:
    """Windows self-update must not touch the locked env: build + launch helper only."""
    from kite.cli import self_manage

    spec = "git+https://github.com/KhanUzeb/kite.git@main"
    script = self_manage._windows_update_script("C:\\uv\\uv.exe", spec, "C:\\Temp\\kite-update.log")
    assert "tool install --force" in script and spec in script
    assert "timeout /t 3" in script and 'del "%~f0"' in script
    assert f'"C:\\uv\\uv.exe" tool install --force "{spec}"\r\n' in script

    uninstall_script = self_manage._windows_uninstall_script("C:\\uv\\uv.exe", "C:\\Temp\\kite-un.log")
    assert "tool uninstall kite" in uninstall_script and "[kite] done" in uninstall_script

    monkeypatch.setattr(self_manage, "_use_detached_handoff", lambda: True)
    monkeypatch.setattr(self_manage, "_managed", lambda: True)
    monkeypatch.setattr("shutil.which", lambda name: f"C:\\bin\\{name}.exe")
    launched: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        "kite.cli.self_manage.subprocess.Popen",
        lambda cmd, **k: launched.append((list(cmd), k)) or MagicMock(),
    )
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    assert self_manage.cmd_update(argparse.Namespace(check=False, force=False, ref=None, repo=None)) == 0
    assert launched and launched[0][0][:2] == ["cmd", "/c"]
    # Console-attached: stdio inherited (streams in the original terminal),
    # no DETACHED_PROCESS flag so output isn't swallowed.
    kwargs = launched[0][1]
    assert kwargs.get("stdout") is None and kwargs.get("stderr") is None
    assert not (int(kwargs.get("creationflags") or 0) & 0x00000008)
    assert (tmp_path / "kite-update-helper.cmd").is_file()


def test_gh_cli_missing_binary_and_child_secret_filtering(monkeypatch, kite_home, capsys) -> None:
    from kite.cli.run import main

    # No gh binary: graceful message, no crash.
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert main(["gh", "issue", "view", "12"]) == 127
    assert "gh CLI not found" in capsys.readouterr().out

    # Token flows to gh children; other secrets stay stripped.
    monkeypatch.setenv("GH_TOKEN", "ghs_test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen: dict = {}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("shutil.which", lambda _name: "gh")
    monkeypatch.setattr(
        "kite.cli.gh.subprocess.run",
        lambda cmd, **kwargs: seen.update(cmd=list(cmd), env=kwargs.get("env")) or _Proc(),
    )
    assert main(["gh", "issue", "view", "12", "--repo", "o/r"]) == 0
    assert seen["cmd"][:4] == ["gh", "issue", "view", "12"]
    assert "--repo" in seen["cmd"] and "o/r" in seen["cmd"]
    assert seen["env"]["GH_TOKEN"] == "ghs_test"
    assert "OPENAI_API_KEY" not in seen["env"]


def test_purge_removes_read_only_files(tmp_path) -> None:
    import os

    from kite.cli.self_manage import _purge_home

    home = tmp_path / ".kite"
    nested = home / "sessions"
    nested.mkdir(parents=True)
    target = nested / "s.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    os.chmod(target, 0o444)
    removed, leftover, error = _purge_home(str(home))
    assert removed and leftover == 0 and error == "" and not home.exists()


def test_main_loads_credentials_except_for_version(monkeypatch, kite_home) -> None:
    calls: list[str] = []
    monkeypatch.setattr("kite.providers.credentials.load_kite_env", lambda: calls.append("load"))
    monkeypatch.setattr("kite.cli.run.cmd_print", lambda args: 7)
    monkeypatch.setattr("kite.cli.setup.maybe_run_first_setup", lambda console: None)
    monkeypatch.setattr("kite.cli.run.cmd_chat", lambda args: 0)
    from kite.cli.run import main

    assert main(["--print", "hello"]) == 7
    assert main([]) == 0
    assert calls == ["load", "load"]
    assert main(["--version"]) == 0
    assert calls == ["load", "load"]


