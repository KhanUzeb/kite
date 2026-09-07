"""Audit log redaction."""

from __future__ import annotations

from kite.memory.audit import AuditLog


def test_audit_redacts_secrets(tmp_path) -> None:
    log = AuditLog(path=tmp_path / "audit.jsonl")
    log.append("tool", output="api_key=sk-abcdefghijklmnopqrstuvwxyz123456")
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "REDACTED" in text
    assert "sk-abc" not in text
