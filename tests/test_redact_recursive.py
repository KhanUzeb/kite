"""Recursive secret redaction."""

from __future__ import annotations

from kite.guardrails.redact import REDACTED, sanitize_payload, sanitize_value


def test_nested_dict_and_list_redacted() -> None:
    payload = {
        "command": "curl -H 'Authorization: Bearer SECRET'",
        "headers": {"Authorization": "Bearer SECRET"},
        "items": [{"token": "SECRET"}],
    }
    out = sanitize_payload(payload)
    text = str(out)
    assert "SECRET" not in text
    assert REDACTED in text
    assert out["headers"]["Authorization"] == REDACTED
    assert out["items"][0]["token"] == REDACTED


def test_nested_tuple_and_set_redacted() -> None:
    value = sanitize_value(
        (
            {"refresh_token": "abc"},
            [{"api_key": "sk-abcdefghijklmnopqrstuvwxyz123456"}],
            {"cookie"},
        )
    )
    text = str(value)
    assert "abc" not in text
    assert "sk-abc" not in text
    assert REDACTED in text


def test_audit_log_nested_secrets(kite_home) -> None:
    from kite.memory.audit import AuditLog

    log = AuditLog()
    log.append(
        "tool",
        tool="bash",
        args={"headers": {"Authorization": "Bearer TOPSECRET"}, "nested": [{"password": "hunter2"}]},
    )
    row = log.tail(1)[0]
    blob = str(row)
    assert "TOPSECRET" not in blob
    assert "hunter2" not in blob
    assert REDACTED in blob


def test_event_payload_nested_redaction() -> None:
    from kite.application.events import redact_payload

    out = redact_payload(
        {
            "tool_args": {
                "command": "curl -H 'Authorization: Bearer XYZ'",
                "env": {"GITHUB_TOKEN": "ghp_abcdefghijklmnopqrst"},
            }
        }
    )
    text = str(out)
    assert "XYZ" not in text
    assert "ghp_" not in text
    assert REDACTED in text
