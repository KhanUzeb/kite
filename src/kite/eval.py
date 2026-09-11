"""Recorded replay and evaluation harness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kite import __version__


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


@dataclass
class ReplayBundle:
    run_id: str
    prompt_hash: str
    context_snapshot_id: str
    config_hash: str
    model: str
    provider: str
    tool_catalog_hash: str
    workspace_fingerprint: str
    harness_version: str = __version__
    policy_version: str = "0.9.0"
    responses: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    acceptance: dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> ReplayBundle:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("events", [])
        data.setdefault("acceptance", {})
        return ReplayBundle(**data)

    def record_event(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append({"kind": kind, "payload": payload})


@dataclass
class ReplayModelBackend:
    responses: list[dict[str, Any]]
    _index: int = 0

    def query(self, messages: list[dict], **kwargs: Any) -> dict:
        if self._index >= len(self.responses):
            return {"role": "assistant", "content": "REPLAY_EXHAUSTED"}
        resp = self.responses[self._index]
        self._index += 1
        return resp


def workspace_fingerprint(workspace: Path) -> str:
    parts = []
    for p in sorted(workspace.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            try:
                parts.append(f"{p.relative_to(workspace)}:{p.stat().st_size}")
            except OSError:
                continue
    return _digest("\n".join(parts))


def config_hash(config: dict[str, Any]) -> str:
    return _digest(json.dumps(config, sort_keys=True))


def tool_catalog_hash(tools: list[dict[str, Any]]) -> str:
    return _digest(json.dumps(tools, sort_keys=True))


def _check_acceptance(bundle: ReplayBundle, result: dict[str, Any]) -> dict[str, Any]:
    checks = bundle.acceptance or {}
    if not checks:
        return {"ok": True, "checks": []}
    failures: list[str] = []
    passed: list[str] = []

    expected_content = checks.get("content_contains")
    if expected_content:
        content = str(result.get("content") or "")
        if expected_content in content:
            passed.append("content_contains")
        else:
            failures.append(f"content missing: {expected_content!r}")

    forbidden = checks.get("content_excludes")
    if forbidden:
        content = str(result.get("content") or "")
        if forbidden in content:
            failures.append(f"content includes forbidden: {forbidden!r}")
        else:
            passed.append("content_excludes")

    min_events = checks.get("min_events")
    if min_events is not None:
        count = len(bundle.events)
        if count >= int(min_events):
            passed.append("min_events")
        else:
            failures.append(f"expected >= {min_events} events, got {count}")

    required_kinds = checks.get("event_kinds")
    if required_kinds:
        kinds = {e.get("kind") for e in bundle.events}
        missing = [k for k in required_kinds if k not in kinds]
        if missing:
            failures.append(f"missing event kinds: {missing}")
        else:
            passed.append("event_kinds")

    return {"ok": not failures, "passed": passed, "failures": failures}


def run_replay(bundle: ReplayBundle) -> dict[str, Any]:
    from kite.application.model import ModelGateway

    backend = ReplayModelBackend(bundle.responses)
    resp = ModelGateway(backend).complete([{"role": "user", "content": "replay task"}])
    result = {
        "ok": True,
        "content": resp.content,
        "responses_used": backend._index,
        "harness_version": bundle.harness_version,
        "policy_version": bundle.policy_version,
        "events_recorded": len(bundle.events),
    }
    acceptance = _check_acceptance(bundle, result)
    result["acceptance"] = acceptance
    if not acceptance.get("ok", True):
        result["ok"] = False
    return result
