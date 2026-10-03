"""Antigravity (`agy` CLI) subscription linkage — no network, no real creds."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kite.providers.auth.antigravity import AntigravityAuthProvider, _auth_url_in_line


def _marker(kite_home: Path) -> Path:
    return kite_home / "oauth" / "antigravity" / "status.json"


def _use_real_auth_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass conftest's autouse OAuth stub so the real registry resolves."""
    from kite.providers.auth import _PROVIDERS

    monkeypatch.setattr("kite.providers.auth.get_auth_provider", _PROVIDERS.get)
    monkeypatch.setattr("kite.providers.byos.get_auth_provider", _PROVIDERS.get)


def _fresh_marker(kite_home: Path) -> None:
    import time

    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"linked": True, "verified_at": time.time(), "verified_via": "agy models"}),
        encoding="utf-8",
    )


def _c_test_auth_url_filter() -> None:
    assert _auth_url_in_line("Visit https://accounts.google.com/o/oauth2/auth?x=1 now") != ""
    assert _auth_url_in_line("see https://antigravity.google/docs/cli/install/") != ""
    assert _auth_url_in_line("callback http://localhost:8080/?code=abc") == ""  # http only
    assert _auth_url_in_line("read https://example.com/docs/update-notes") == ""
    assert _auth_url_in_line("no url here") == ""


def _c_test_status_states(monkeypatch: pytest.MonkeyPatch, kite_home: Path) -> None:
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: None)
    missing = AntigravityAuthProvider().status()
    assert missing.authenticated is False
    assert "antigravity.google" in missing.message

    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    calls: list[str] = []
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session",
        lambda **_k: (calls.append("probe") or (False, ())),
    )
    assert not _marker(kite_home).exists()
    unlinked = AntigravityAuthProvider().status()
    assert unlinked.authenticated is False
    assert "kite login antigravity" in unlinked.message
    assert calls == ["probe"]

    # Fresh verified marker: fast path, no subprocess probe.
    calls.clear()
    _fresh_marker(kite_home)
    linked = AntigravityAuthProvider().status()
    assert linked.authenticated is True
    assert calls == []

    # Stale marker + failed probe: session is gone, marker is cleared.
    stale = _marker(kite_home)
    stale.write_text(json.dumps({"linked": True, "verified_at": 0.0}), encoding="utf-8")
    gone = AntigravityAuthProvider().status()
    assert gone.authenticated is False
    assert not stale.exists()

    # Live probe success marks linked.
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session",
        lambda **_k: (True, ("gemini-3.8-flash-medium",)),
    )
    verified = AntigravityAuthProvider().status()
    assert verified.authenticated is True
    assert _marker(kite_home).is_file()


def _c_test_login_headless_verifies_probe(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Headless login surfaces the sign-in URL and marks linked only on probe success."""
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    monkeypatch.setattr("kite.util.tty.is_interactive_tty", lambda **_k: False)
    # Probe fails before sign-in (status short-circuit skipped), succeeds after.
    probe_calls: list[str] = []

    def fake_probe(**_k):
        probe_calls.append("probe")
        if len(probe_calls) == 1:
            return False, ()
        return True, ("gemini-3.8-flash-medium", "claude-sonnet-4-6")

    monkeypatch.setattr("kite.providers.auth.antigravity.probe_session", fake_probe)

    opened: list[str] = []
    monkeypatch.setattr(
        "kite.providers.auth.ui.open_browser",
        lambda url: opened.append(url) or True,
    )

    def fake_stream(cmd, *args, timeout=0.0, on_line=None, env=None):
        if on_line is not None:
            on_line("Some telemetry: https://example.com/docs\n")
            on_line("Visit https://accounts.google.com/o/oauth2/auth?client_id=abc to sign in\n")
        return subprocess.CompletedProcess([cmd, *args], 0, "ok", "")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", fake_stream)

    result = AntigravityAuthProvider().login(console=None)

    assert result.exit_code == 0
    # Only the auth URL is surfaced — never docs/telemetry links.
    assert opened and opened[0].startswith("https://accounts.google.com/")
    assert all("example.com" not in url for url in opened)
    marker = _marker(kite_home)
    assert marker.is_file()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["linked"] is True and payload["verified_via"] == "agy models"
    assert "signed-in agy CLI" in result.message and "gemini" in result.message

    # Short-circuit when freshly verified: must not spawn agy again.
    def _fail(*_a: object, **_k: object) -> object:
        raise AssertionError("must not spawn agy when already linked")

    monkeypatch.setattr("kite.providers.auth.cli.run_cli_streaming", _fail)
    monkeypatch.setattr("kite.providers.auth.antigravity.probe_session", _fail)
    again = AntigravityAuthProvider().login(console=None)
    assert again.exit_code == 0
    assert "already linked" in again.message


def _c_test_login_exit_zero_without_session_fails(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quitting agy (exit 0) without signing in must NOT mark linked."""
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    monkeypatch.setattr("kite.util.tty.is_interactive_tty", lambda **_k: False)
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (False, ())
    )
    monkeypatch.setattr(
        "kite.providers.auth.cli.run_cli_streaming",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "bye", ""),
    )
    result = AntigravityAuthProvider().login(console=None)
    assert result.exit_code == 2
    assert "did not complete" in result.message
    assert not _marker(kite_home).exists()


def _c_test_logout_clears_marker(kite_home: Path) -> None:
    auth = AntigravityAuthProvider()
    assert auth.logout() is False
    marker = _marker(kite_home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"linked": True}), encoding="utf-8")
    assert auth.logout() is True
    assert not marker.exists()


def _c_test_registry_session_and_credentials(
    kite_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kite.providers.auth as auth_mod
    from kite.providers.auth import _PROVIDERS, resolve_login_provider
    from kite.providers.byos import has_oauth_session
    from kite.providers.catalog import load_catalog
    from kite.providers.credentials import inspect_provider_credentials

    _use_real_auth_registry(monkeypatch)
    assert resolve_login_provider("antigravity-sub") == "antigravity"
    # Module-attribute access: `from x import y` would keep the conftest stub.
    assert isinstance(auth_mod.get_auth_provider("antigravity"), AntigravityAuthProvider)
    assert _PROVIDERS["antigravity"].provider_key == "antigravity"

    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (False, ())
    )
    assert has_oauth_session("antigravity") is False
    _fresh_marker(kite_home)
    # Status verdicts are cached — a marker transition invalidates
    # (login_oauth/logout_oauth do this in production).
    from kite.providers.byos import invalidate_auth_status_cache

    invalidate_auth_status_cache("antigravity")
    assert has_oauth_session("antigravity") is True

    spec = load_catalog().get("antigravity")
    assert spec.oauth_provider == "antigravity"
    fresh_marker = _marker(kite_home)
    fresh_marker.unlink()
    # Direct file removal (production logout invalidates the verdict cache).
    invalidate_auth_status_cache("antigravity")
    assert inspect_provider_credentials(spec).usable is False

    _fresh_marker(kite_home)
    invalidate_auth_status_cache("antigravity")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    linked_only = inspect_provider_credentials(spec)
    assert linked_only.linked is True and linked_only.usable is True
    assert "agy" in linked_only.detail

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    ready = inspect_provider_credentials(spec)
    assert ready.linked is True and ready.usable is True


def _c_test_fetch_model_ids_probe_and_fallback(kite_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live = ("gemini-3.8-flash-medium", "claude-sonnet-4-6")
    # Pin the binary too: CI runners have no `agy`, and without it the
    # provider correctly falls back instead of probing.
    monkeypatch.setattr("kite.providers.auth.antigravity.agy_cli_path", lambda: "agy")
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (True, live)
    )
    assert AntigravityAuthProvider().fetch_model_ids() == live
    monkeypatch.setattr(
        "kite.providers.auth.antigravity.probe_session", lambda **_k: (False, ())
    )
    assert AntigravityAuthProvider().fetch_model_ids() == (
        "gemini-3.8-flash-medium",
        "gemini-3.7-flash-medium",
        "gemini-3.1-pro-high",
        "claude-sonnet-4-6",
    )
    assert AntigravityAuthProvider().litellm_env() == {}
    assert AntigravityAuthProvider().litellm_extras() == {}


def _c_test_agy_exec_argv_prompt_and_payload() -> None:
    from kite.providers.auth.antigravity_exec import (
        AntigravityExecError,
        AntigravityQuotaError,
        build_agy_argv,
        flatten_prompt,
        parse_agy_payload,
    )

    argv = build_agy_argv(model="gemini-3.7-flash-medium")
    assert argv[:3] == [argv[0], "--model", "gemini-3.7-flash-medium"]
    assert "--mode" in argv and "plan" in argv and "--output-format" in argv
    assert "-p" not in argv  # prompt travels on stdin (WinError 206)
    bare = build_agy_argv(model="gemini-2.5-pro", with_model=False)
    assert "--model" not in bare

    prompt = flatten_prompt(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "tool_calls": [{"function": {"name": "read"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "x"},
        ]
    )
    assert "<system>\nbe brief" in prompt and "User: hello" in prompt
    assert "tool calls requested" in prompt and "tool_call_id" not in prompt

    ok = parse_agy_payload(
        {"status": "OK", "response": "done", "usage": {"input_tokens": 10, "output_tokens": 4}}
    )
    assert (ok.text, ok.input_tokens, ok.output_tokens) == ("done", 10, 4)
    # Real quota-exhausted shape: retrying cannot help → dedicated error.
    try:
        parse_agy_payload(
            {
                "status": "ERROR",
                "response": "",
                "error": "Individual quota reached. Please upgrade your subscription "
                "to increase your limits. Resets in 66h44m32s.",
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
        )
    except AntigravityQuotaError as exc:
        assert "quota" in str(exc).lower()
    else:
        raise AssertionError("quota error must raise AntigravityQuotaError")
    try:
        parse_agy_payload({"status": "ERROR", "response": "", "error": "boom"})
    except AntigravityExecError:
        pass
    else:
        raise AssertionError("plain agy error must raise AntigravityExecError")


def _c_test_agy_turn_retries_without_model_on_unknown_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from kite.providers.auth import antigravity_exec as exec_mod

    monkeypatch.setattr(exec_mod, "agy_executable", lambda: "agy")
    seen: list[tuple[list[str], str]] = []

    def _fake_run(argv: list[str], **_k: object) -> str:
        seen.append((argv, str(_k.get("input_text") or "")))
        import json as _json

        if "--model" in argv:
            return _json.dumps({"status": "ERROR", "response": "", "error": "unknown model 'x'"})
        return _json.dumps({"status": "OK", "response": "hi", "usage": {}})

    monkeypatch.setattr(exec_mod, "_run_agy_process", _fake_run)
    turn = exec_mod.run_agy_turn(model="gemini-2.5-pro", messages=[{"role": "user", "content": "hi"}])
    assert turn.text == "hi"
    assert len(seen) == 2 and "--model" not in seen[1][0]
    assert all("User: hi" in stdin for _, stdin in seen)  # prompt via stdin


def test_batch_00(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_auth_url_filter, test_status_states, test_login_headless_verifies_probe."""
    _c_test_auth_url_filter()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k0_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_status_states(kite_home=_k1, monkeypatch=_mp1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k0_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_login_headless_verifies_probe(kite_home=_k2, monkeypatch=_mp2)
    finally:
        _mp2.undo()

def test_batch_01(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_login_exit_zero_without_session_fails, test_logout_clears_marker, test_registry_session_and_credentials."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k1_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_login_exit_zero_without_session_fails(kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _mp1 = pytest.MonkeyPatch()
    try:
        _k1 = tmp_path / "k1_1"
        _k1.mkdir(parents=True, exist_ok=True)
        _mp1.setenv("KITE_HOME", str(_k1))
        _c_test_logout_clears_marker(kite_home=_k1)
    finally:
        _mp1.undo()
    _mp2 = pytest.MonkeyPatch()
    try:
        _k2 = tmp_path / "k1_2"
        _k2.mkdir(parents=True, exist_ok=True)
        _mp2.setenv("KITE_HOME", str(_k2))
        _c_test_registry_session_and_credentials(kite_home=_k2, monkeypatch=_mp2)
    finally:
        _mp2.undo()

def test_batch_02(tmp_path) -> None:
    """Consolidated (bodies unchanged): test_fetch_model_ids_probe_and_fallback, test_agy_exec_argv_prompt_and_payload, test_agy_turn_retries_without_model_on_unknown_model."""
    _mp0 = pytest.MonkeyPatch()
    try:
        _k0 = tmp_path / "k2_0"
        _k0.mkdir(parents=True, exist_ok=True)
        _mp0.setenv("KITE_HOME", str(_k0))
        _c_test_fetch_model_ids_probe_and_fallback(kite_home=_k0, monkeypatch=_mp0)
    finally:
        _mp0.undo()
    _c_test_agy_exec_argv_prompt_and_payload()
    _mp2 = pytest.MonkeyPatch()
    try:
        _c_test_agy_turn_retries_without_model_on_unknown_model(monkeypatch=_mp2)
    finally:
        _mp2.undo()

