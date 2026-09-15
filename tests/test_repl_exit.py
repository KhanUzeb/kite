"""Issue #84 — copy-pasteable resume hint on interactive exit."""

from __future__ import annotations

from io import StringIO

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


def test_print_resume_hint_contains_session_id(tmp_path, kite_home, monkeypatch) -> None:
    from kite.memory.session import create_session

    created = create_session(task="demo", cwd=str(tmp_path), provider="p", model="m")
    session = _quiet_session(tmp_path, monkeypatch)
    session._session_id = created.id
    session._print_resume_hint()
    out = _out(session)
    assert "Resume this session with" in out
    assert f"kite resume {created.id}" in out


def test_print_resume_hint_absent_without_session(tmp_path, kite_home, monkeypatch) -> None:
    session = _quiet_session(tmp_path, monkeypatch)
    assert session._session_id is None
    session._print_resume_hint()
    assert "Resume this session" not in _out(session)


def test_print_resume_hint_absent_when_not_persisted(tmp_path, kite_home, monkeypatch) -> None:
    session = _quiet_session(tmp_path, monkeypatch)
    session._session_id = "nope-not-persisted-0000"
    session._print_resume_hint()
    assert "Resume this session" not in _out(session)


def test_print_resume_hint_never_leaks_secrets(tmp_path, kite_home, monkeypatch) -> None:
    from kite.memory.session import create_session

    secret = "sk-ant-testsecret-does-not-leave-hint-999"
    created = create_session(task=f"fix bug key={secret}", cwd=str(tmp_path), provider="p", model="m")
    session = _quiet_session(tmp_path, monkeypatch)
    session._session_id = created.id
    session._print_resume_hint()
    out = _out(session)
    assert created.id in out
    assert secret not in out


def test_run_eof_prints_resume_hint(tmp_path, kite_home, monkeypatch) -> None:
    from kite.memory.session import create_session
    from kite.ui.complete import ComposerResult

    created = create_session(task="demo", cwd=str(tmp_path), provider="p", model="m")
    session = _quiet_session(tmp_path, monkeypatch)
    session._session_id = created.id
    session._read_input = lambda: ComposerResult("eof")  # type: ignore[method-assign]
    assert session.run() == 0
    out = _out(session)
    assert "bye" in out
    assert f"kite resume {created.id}" in out


def test_run_quit_prints_resume_hint(tmp_path, kite_home, monkeypatch) -> None:
    from kite.memory.session import create_session
    from kite.ui.complete import ComposerResult

    created = create_session(task="demo", cwd=str(tmp_path), provider="p", model="m")
    session = _quiet_session(tmp_path, monkeypatch)
    session._session_id = created.id
    prompts = [ComposerResult("text", "/quit")]
    session._read_input = lambda: prompts.pop(0)  # type: ignore[method-assign]
    assert session.run() == 0
    out = _out(session)
    assert "bye" in out
    assert f"kite resume {created.id}" in out


def test_run_eof_without_session_has_no_hint(tmp_path, kite_home, monkeypatch) -> None:
    from kite.ui.complete import ComposerResult

    session = _quiet_session(tmp_path, monkeypatch)
    session._read_input = lambda: ComposerResult("eof")  # type: ignore[method-assign]
    assert session.run() == 0
    out = _out(session)
    assert "bye" in out
    assert "Resume this session" not in out
