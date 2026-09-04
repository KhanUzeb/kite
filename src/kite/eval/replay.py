"""Recorded replay and evaluation harness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kite import __version__


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> ReplayBundle:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReplayBundle(**data)


@dataclass
class ReplayModelBackend:
    """Serve recorded responses without live provider access."""

    responses: list[dict[str, Any]]
    _index: int = 0

    def query(self, messages: list[dict], **kwargs: Any) -> dict:
        if self._index >= len(self.responses):
            return {"role": "assistant", "content": "REPLAY_EXHAUSTED"}
        resp = self.responses[self._index]
        self._index += 1
        return resp


def workspace_fingerprint(workspace: Path) -> str:
    parts: list[str] = []
    for p in sorted(workspace.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            try:
                parts.append(f"{p.relative_to(workspace)}:{p.stat().st_size}")
            except OSError:
                continue
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def tool_catalog_hash(tools: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest()[:16]


def run_replay(bundle: ReplayBundle) -> dict[str, Any]:
    from kite.application.model.gateway import ModelGateway

    backend = ReplayModelBackend(bundle.responses)
    gw = ModelGateway(backend)
    messages = [{"role": "user", "content": "replay task"}]
    resp = gw.complete(messages)
    return {
        "ok": True,
        "content": resp.content,
        "responses_used": backend._index,
        "harness_version": bundle.harness_version,
        "policy_version": bundle.policy_version,
    }
