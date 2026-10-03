"""Issue #84 — copy-pasteable resume hint on interactive exit."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from kite.ui.repl import ChatSession
from tests.conftest import strip_ansi


def _quiet_session(tmp_path, monkeypatch) -> ChatSession:
    monkeypatch.setattr(ChatSession, "_schedule_release_check_legacy", lambda self: None)
    monkeypatch.setattr(ChatSession, "_prewarm_composer", lambda self: None)
    monkeypatch.setattr(ChatSession, "_startup_banner", lambda self: None)
    monkeypatch.setattr(ChatSession, "_maybe_prompt_project_trust", lambda self: None)
    session = ChatSession(cwd=str(tmp_path))
    buf = StringIO()
    session.console = Console(file=buf, force_terminal=False)
    session._buf = buf  # type: ignore[attr-defined]
    return session


def _out(session: ChatSession) -> str:
    return strip_ansi(session._buf.getvalue())  # type: ignore[attr-defined]


def _c_test_resume_exe_ignores_generic_launchers(monkeypatch) -> None:
    import sys

    from kite.ui import repl as repl_mod

    monkeypatch.setattr("shutil.which", lambda _name: None)
    for argv0 in (
        "/usr/lib/python3.12/site-packages/pytest/__main__.py",
        "/usr/local/bin/pytest",
        "/usr/bin/python3",
        "",
    ):
        monkeypatch.setattr(sys, "argv", [argv0])
        assert repl_mod._resume_exe() == "kite", argv0
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/kite-dev"])
    assert repl_mod._resume_exe() == "kite-dev"
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/kite" if name == "kite" else None)
    monkeypatch.setattr(sys, "argv", ["whatever"])
    assert repl_mod._resume_exe() == "kite"


def _c_test_print_resume_hint_states(tmp_path, kite_home, monkeypatch) -> None:
    from kite.memory.session import create_session

    created = create_session(task="demo", cwd=str(tmp_path), provider="p", model="m")
    session = _quiet_session(tmp_path, monkeypatch)
    session._session_id = created.id
    session._print_resume_hint()
    out = _out(session)
    assert "Resume this session with" in out
    assert f"kite resume {created.id}" in out

    # Absent without any session.
    nosession = _quiet_session(tmp_path, monkeypatch)
    assert nosession._session_id is None
    nosession._print_resume_hint()
    assert "Resume this session" not in _out(nosession)

    # Absent when the id was never persisted.
    stale = _quiet_session(tmp_path, monkeypatch)
    stale._session_id = "nope-not-persisted-0000"
    stale._print_resume_hint()
    assert "Resume this session" not in _out(stale)

    # Persisted hint never leaks secrets from the task text.
    secret = "sk-ant-testsecret-does-not-leave-hint-999"
    secreted = create_session(task=f"fix bug key={secret}", cwd=str(tmp_path), provider="p", model="m")
    secret_session = _quiet_session(tmp_path, monkeypatch)
    secret_session._session_id = secreted.id
    secret_session._print_resume_hint()
    secret_out = _out(secret_session)
    assert secreted.id in secret_out
    assert secret not in secret_out


def _c_test_run_eof_and_quit_print_resume_hint(tmp_path, kite_home, monkeypatch) -> None:
    from kite.memory.session import create_session
    from kite.ui.complete import ComposerResult

    eof_created = create_session(task="demo", cwd=str(tmp_path), provider="p", model="m")
    eof_session = _quiet_session(tmp_path, monkeypatch)
    eof_session._session_id = eof_created.id
    eof_session._read_input = lambda: ComposerResult("eof")  # type: ignore[method-assign]
    assert eof_session.run() == 0
    eof_out = _out(eof_session)
    assert "bye" in eof_out
    assert f"kite resume {eof_created.id}" in eof_out

    quit_created = create_session(task="demo", cwd=str(tmp_path), provider="p", model="m")
    quit_session = _quiet_session(tmp_path, monkeypatch)
    quit_session._session_id = quit_created.id
    prompts = [ComposerResult("text", "/quit")]
    quit_session._read_input = lambda: prompts.pop(0)  # type: ignore[method-assign]
    assert quit_session.run() == 0
    quit_out = _out(quit_session)
    assert "bye" in quit_out
    assert f"kite resume {quit_created.id}" in quit_out


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_resume_exe_ignores_generic_launchers, test_print_resume_hint_states, test_run_eof_and_quit_print_resume_hint."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _c_test_resume_exe_ignores_generic_launchers(monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _t1 = tmp_path / "t0_1"
        _t1.mkdir(parents=True, exist_ok=True)
        _k1 = tmp_path / "k0_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_print_resume_hint_states(tmp_path=_t1, kite_home=_k1, monkeypatch=_mp1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _t2 = tmp_path / "t0_2"
        _t2.mkdir(parents=True, exist_ok=True)
        _k2 = tmp_path / "k0_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_run_eof_and_quit_print_resume_hint(tmp_path=_t2, kite_home=_k2, monkeypatch=_mp2)
    finally:
        _mp2.undo()

