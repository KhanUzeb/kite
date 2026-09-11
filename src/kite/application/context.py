"""Bounded prompt-context snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from kite.application.contracts import RunSpec
from kite.context.discovery import gather_project_context

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


def compute_prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


TRUSTED_LEVELS: frozenset[TrustLevel] = frozenset(
    {"trusted_runtime_policy", "trusted_user_instruction", "trusted_project_instruction"},
)


def render_item(item: ContextItem) -> str:
    if item.trust_level in TRUSTED_LEVELS:
        return item.content
    open_tag = f"<!-- kite:untrusted source={item.source} trust={item.trust_level} -->"
    return f"{open_tag}\n{item.content.strip()}\n<!-- /kite:untrusted -->"


def render_snapshot(items: tuple[ContextItem, ...]) -> str:
    return "\n\n".join(r for item in items if (r := render_item(item).strip()))


def inspect_snapshot(snapshot: ContextSnapshot) -> dict[str, Any]:
    from kite.application.events import redact_text

    items = [
        {
            "item_id": item.item_id,
            "source": item.source,
            "trust_level": item.trust_level,
            "token_cost": item.token_cost,
            "inclusion_reason": snapshot.inclusion_map.get(item.item_id, "selected"),
            "provenance": item.provenance,
            "content_preview": redact_text(item.content[:240]),
        }
        for item in snapshot.items
    ]
    return {
        "run_id": snapshot.run_id,
        "prompt_hash": snapshot.prompt_hash,
        "assembler_version": snapshot.assembler_version,
        "total_tokens": sum(i.token_cost for i in snapshot.items),
        "budget_input": snapshot.budget.input_budget(),
        "items": items,
        "omitted": [
            {"item_id": o.item_id, "source": o.source, "reason": o.reason, "token_cost": o.token_cost}
            for o in snapshot.omitted_items
        ],
    }


@dataclass
class CompactionState:
    constraints: list[str] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    changed_hashes: dict[str, str] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cwd: str = ""
    execution_mode: str = "restricted"
    provider: str = ""
    model: str = ""
    budget_state: dict[str, Any] = field(default_factory=dict)
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_ids: list[str] = field(default_factory=list)


def extract_compaction_state(
    messages: list[dict],
    *,
    cwd: str = "",
    todos: list[dict] | None = None,
    session_meta: dict | None = None,
) -> CompactionState:
    from kite.context.window import extract_compaction_facts

    meta = session_meta or {}
    state = CompactionState(
        cwd=cwd,
        todos=list(todos or []),
        constraints=[f for f in extract_compaction_facts(messages) if f.startswith("constraint:")],
        provider=str(meta.get("provider") or ""),
        model=str(meta.get("model") or ""),
        execution_mode=str(meta.get("execution_mode") or "restricted"),
    )
    pending: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            pending.extend(msg["tool_calls"])
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id")
            pending = [p for p in pending if p.get("id") != tc_id]
    state.pending_tool_calls = pending
    return state


def pair_tool_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        out.append(msg)
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            ids = {tc.get("id") for tc in msg["tool_calls"]}
            j = i + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                if messages[j].get("tool_call_id") in ids:
                    out.append(messages[j])
                j += 1
            i = j
            continue
        i += 1
    return out





class ContextAssembler:
    """Single entry for building provenance-aware context snapshots."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()
        self.assembler_version = ASSEMBLER_VERSION

    def build(self, spec: RunSpec, sources: dict[str, Any] | None = None) -> ContextSnapshot:
        sources = sources or {}
        run_id = spec.run_id or "pending"
        items: list[ContextItem] = []
        omitted: list[OmittedItem] = []
        inclusion: dict[str, InclusionReason] = {}
        seen_content: set[str] = set()

        def _omit(item: ContextItem, reason: OmissionReason) -> None:
            omitted.append(OmittedItem(item.item_id, item.source, reason, item.token_cost))

        def _add(item: ContextItem, reason: InclusionReason = "selected") -> None:
            key = f"{item.source}:{item.content[:200]}"
            if key in seen_content:
                _omit(item, "duplicate")
                return
            used = sum(i.token_cost for i in items if i.source == item.source)
            if used + item.token_cost > self.budget.source_limit(item.source):
                _omit(item, "budget_exceeded")
                return
            if sum(i.token_cost for i in items) + item.token_cost > self.budget.input_budget():
                _omit(item, "budget_exceeded")
                return
            seen_content.add(key)
            items.append(item)
            inclusion[item.item_id] = reason

        # Stage 1–2: runtime policy + user task
        _add(
            ContextItem.create(
                source="runtime_policy",
                kind="execution_policy",
                content=f"execution_mode={spec.execution_mode or 'restricted'}; approval={spec.approval_mode}",
                provenance="harness",
                trust_level="trusted_runtime_policy",
                priority=100,
            ),
            reason="required",
        )
        _add(
            ContextItem.create(
                source="user",
                kind="task",
                content=spec.task,
                provenance="run_spec",
                trust_level="trusted_user_instruction",
                priority=100,
            ),
            reason="required",
        )

        # Stage 3: project instructions
        if not spec.no_context:
            ctx = sources.get("project_context")
            if ctx is None:
                ctx = gather_project_context(str(spec.workspace))
            if hasattr(ctx, "render_for_prompt"):
                text = ctx.render_for_prompt(max_chars=self.budget.project_instructions * 4)
            else:
                text = str(ctx)
            if text.strip():
                _add(
                    ContextItem.create(
                        source="project_instructions",
                        kind="project_context",
                        content=text,
                        provenance=str(spec.workspace),
                        trust_level="trusted_project_instruction",
                        priority=90,
                    ),
                )

        # Stage 4–6: skills, memory (from sources dict)
        for skill in sources.get("skills") or []:
            body = skill.body if hasattr(skill, "body") else str(skill)
            name = skill.name if hasattr(skill, "name") else "skill"
            _add(
                ContextItem.create(
                    source="skills",
                    kind="skill",
                    content=body,
                    provenance=name,
                    trust_level="external_content",
                    priority=60,
                ),
            )

        for mem in sources.get("memory") or []:
            _add(
                ContextItem.create(
                    source="memory",
                    kind="memory",
                    content=str(mem.get("content", mem)),
                    provenance=str(mem.get("scope", "run")),
                    trust_level="memory",
                    priority=55,
                ),
            )

        # Stage 7–9: tools, history, run state
        tool_schemas = sources.get("tool_schemas") or []
        if tool_schemas:
            schema_text = json.dumps(tool_schemas, indent=0)[: self.budget.tools * 4]
            _add(
                ContextItem.create(
                    source="tools",
                    kind="tool_schemas",
                    content=schema_text,
                    provenance="tool_registry",
                    trust_level="trusted_runtime_policy",
                    priority=95,
                ),
                reason="required",
            )

        for msg in sources.get("history") or []:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:2000]
            _add(
                ContextItem.create(
                    source="history",
                    kind=f"message_{role}",
                    content=content,
                    provenance="conversation",
                    trust_level="tool_observation" if role == "tool" else "model_generated_summary",
                    priority=40,
                ),
            )

        run_state = sources.get("run_state") or {}
        if run_state:
            _add(
                ContextItem.create(
                    source="run_state",
                    kind="run_state",
                    content=json.dumps(run_state, indent=0)[: self.budget.run_state * 4],
                    provenance="harness",
                    trust_level="trusted_runtime_policy",
                    priority=85,
                ),
            )

        rendered = render_snapshot(tuple(items))
        prompt_hash = compute_prompt_hash(rendered)

        return ContextSnapshot(
            run_id=run_id,
            items=tuple(items),
            budget=self.budget,
            omitted_items=tuple(omitted),
            prompt_hash=prompt_hash,
            assembler_version=self.assembler_version,
            rendered_prompt=rendered,
            inclusion_map=inclusion,
        )
