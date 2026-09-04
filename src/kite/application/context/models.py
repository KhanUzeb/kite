"""Context data model — items, budgets, snapshots."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

TrustLevel = Literal[
    "trusted_runtime_policy",
    "trusted_user_instruction",
    "trusted_project_instruction",
    "repository_data",
    "tool_observation",
    "memory",
    "external_content",
    "model_generated_summary",
]

ContextSource = Literal[
    "runtime_policy",
    "user",
    "project_instructions",
    "run_state",
    "skills",
    "memory",
    "repository",
    "tools",
    "history",
    "compaction",
]

InclusionReason = Literal["required", "selected", "budget_fit", "deduplicated"]
OmissionReason = Literal["budget_exceeded", "duplicate", "expired", "low_priority", "trust_filtered"]

ASSEMBLER_VERSION = "0.9.0"


@dataclass(frozen=True, slots=True)
class ContextItem:
    item_id: str
    source: ContextSource
    kind: str
    content: str
    provenance: str
    trust_level: TrustLevel
    priority: int = 50
    token_cost: int = 0
    token_limit: int | None = None
    created_at: str = ""
    expires_at: str | None = None
    redaction_policy: str = "default"

    @staticmethod
    def create(
        *,
        source: ContextSource,
        kind: str,
        content: str,
        provenance: str,
        trust_level: TrustLevel,
        priority: int = 50,
        token_cost: int | None = None,
    ) -> ContextItem:
        cost = token_cost if token_cost is not None else max(1, len(content) // 4)
        return ContextItem(
            item_id=str(uuid.uuid4()),
            source=source,
            kind=kind,
            content=content,
            provenance=provenance,
            trust_level=trust_level,
            priority=priority,
            token_cost=cost,
            created_at=datetime.now(UTC).isoformat(),
        )


@dataclass(frozen=True, slots=True)
class ContextBudget:
    total: int = 128_000
    system: int = 8_000
    user: int = 16_000
    project_instructions: int = 12_000
    repository: int = 24_000
    skills: int = 8_000
    memory: int = 8_000
    tools: int = 12_000
    history: int = 32_000
    run_state: int = 4_000
    response_reserve: int = 16_384

    def source_limit(self, source: ContextSource) -> int:
        mapping: dict[ContextSource, int] = {
            "runtime_policy": self.system,
            "user": self.user,
            "project_instructions": self.project_instructions,
            "run_state": self.run_state,
            "skills": self.skills,
            "memory": self.memory,
            "repository": self.repository,
            "tools": self.tools,
            "history": self.history,
            "compaction": self.history,
        }
        return mapping.get(source, self.total // 8)

    def input_budget(self) -> int:
        return max(0, self.total - self.response_reserve)


@dataclass(frozen=True, slots=True)
class OmittedItem:
    item_id: str
    source: ContextSource
    reason: OmissionReason
    token_cost: int


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    run_id: str
    items: tuple[ContextItem, ...]
    budget: ContextBudget
    omitted_items: tuple[OmittedItem, ...]
    prompt_hash: str
    assembler_version: str = ASSEMBLER_VERSION
    rendered_prompt: str = ""
    inclusion_map: dict[str, InclusionReason] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "prompt_hash": self.prompt_hash,
            "assembler_version": self.assembler_version,
            "item_count": len(self.items),
            "omitted_count": len(self.omitted_items),
            "budget_total": self.budget.total,
        }


def compute_prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
