"""Fullscreen UI projection — fluid stream, no semantic timeline taxonomy."""

from __future__ import annotations

from dataclasses import dataclass, field

from kite.ui.fullscreen.mode import UiDisplayMode


@dataclass(slots=True)
class StreamLine:
    id: str
    mark: str
    label: str
    detail: str = ""
    status: str = "running"


@dataclass(slots=True)
class ChangeFile:
    path: str
    added: int = 0
    deleted: int = 0


@dataclass(slots=True)
class VerificationCheck:
    name: str
    status: str
    summary: str = ""


@dataclass(slots=True)
class AgentWorker:
    name: str
    status: str


@dataclass
class ComposerState:
    attachments: list[str] = field(default_factory=list)
    mode: str = "build"
    provider: str = ""
    model: str = ""
    approval: str = ""
    queued: int = 0


@dataclass
class ApprovalState:
    active: bool = False
    tool: str = ""
    summary: str = ""
    risk: str = ""
    scope: str = ""
    mandatory: bool = False


@dataclass
class ReviewState:
    files: list[ChangeFile] = field(default_factory=list)
    total_added: int = 0
    total_deleted: int = 0
    verified: bool = False
    verification_label: str = "unverified"


@dataclass
class FullscreenModel:
    run_id: str = ""
    display_mode: UiDisplayMode = "compact"
    status: str = "idle"
    mode: str = "build"
    provider: str = ""
    model: str = ""
    branch: str = ""
    repo: str = ""
    cost: float = 0.0
    turn: int = 0
    plan_done: int = 0
    plan_total: int = 0
    active_tool: str = ""
    stream: list[StreamLine] = field(default_factory=list)
    composer: ComposerState = field(default_factory=ComposerState)
    approval: ApprovalState = field(default_factory=ApprovalState)
    review: ReviewState = field(default_factory=ReviewState)
    verification_checks: list[VerificationCheck] = field(default_factory=list)
    agents: list[AgentWorker] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    context_pct: float = 0.0
