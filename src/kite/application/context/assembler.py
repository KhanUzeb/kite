"""Bounded context assembly with source-specific budgets."""

from __future__ import annotations

import json
from typing import Any

from kite.application.context.models import (
    ASSEMBLER_VERSION,
    ContextBudget,
    ContextItem,
    ContextSnapshot,
    InclusionReason,
    OmissionReason,
    OmittedItem,
    compute_prompt_hash,
    render_snapshot,
)
from kite.application.contracts import RunSpec
from kite.context.discovery import gather_project_context


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
