"""Run-centric UI state — explicit projections, never mutated by widgets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kite.ui.cockpit.mode import UiDisplayMode

TimelineKind = Literal[
    "goal",
    "plan",
    "reason",
    "tool",
    "change",
    "approval",
    "verification",
    "checkpoint",
    "handoff",
    "result",
    "error",
]

TimelineStatus = Literal["pending", "running", "ok", "failed", "blocked", "skipped"]


@dataclass(slots=True)
class TimelineEntry:
    id: str
    kind: TimelineKind
    status: TimelineStatus
    title: str
    detail: str = ""
    timestamp: str = ""
    duration_ms: int | None = None
    affected_files: tuple[str, ...] = ()
    collapsed: bool = True
    tool: str = ""
    sequence: int = 0


@dataclass(slots=True)
class ChangeFile:
    path: str
    added: int = 0
    deleted: int = 0


@dataclass
class ComposerState:
    attachments: list[str] = field(default_factory=list)
    mode: str = "build"
    provider: str = ""
    model: str = ""
    approval: str = ""
    queued: int = 0
    steer_pending: bool = False


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
    selected_path: str | None = None
    verified: bool = False
    verification_label: str = "unverified"


@dataclass
class VerificationCheck:
    name: str
    status: str  # pass | fail | pending | skip
    summary: str = ""


@dataclass
class AgentWorker:
    name: str
    status: str  # queued | running | completed | failed
    objective: str = ""


@dataclass
class AgentState:
    workers: list[AgentWorker] = field(default_factory=list)


@dataclass
class ContextState:
    pct: float = 0.0
    files: int = 0
    memories: int = 0
    tools: int = 0
    window: int = 0
    tokens: int = 0


@dataclass
class PanelState:
    work_focus: str = "active"
    inspect_focus: str = "status"
    timeline_expanded: set[str] = field(default_factory=set)


@dataclass
class RunViewModel:
    """Projection of one agent run for compact TUI and cockpit."""

    run_id: str = ""
    goal: str = ""
    status: str = "idle"
    mode: str = "build"
    provider: str = ""
    model: str = ""
    branch: str = ""
    repo: str = ""
    turn: int = 0
    cost: float = 0.0
    display_mode: UiDisplayMode = "compact"
    timeline: list[TimelineEntry] = field(default_factory=list)
    composer: ComposerState = field(default_factory=ComposerState)
    approval: ApprovalState = field(default_factory=ApprovalState)
    review: ReviewState = field(default_factory=ReviewState)
    context: ContextState = field(default_factory=ContextState)
    agents: AgentState = field(default_factory=AgentState)
    panels: PanelState = field(default_factory=PanelState)
    plan_done: int = 0
    plan_total: int = 0
    verification_checks: list[VerificationCheck] = field(default_factory=list)
    active_tool: str = ""
    errors: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "turn": self.turn,
            "timeline_count": len(self.timeline),
            "changes": len(self.review.files),
            "verified": self.review.verified,
            "approval_active": self.approval.active,
            "display_mode": self.display_mode,
        }
