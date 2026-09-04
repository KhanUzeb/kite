"""Context inspection — explain inclusion/omission with redaction."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from kite.application.context.models import ContextSnapshot

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
)


@dataclass(frozen=True, slots=True)
class ContextInspectionRow:
    item_id: str
    source: str
    trust_level: str
    token_cost: int
    inclusion_reason: str
    provenance: str
    content_preview: str


def redact_secrets(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def inspect_snapshot(snapshot: ContextSnapshot) -> dict[str, Any]:
    rows: list[ContextInspectionRow] = []
    for item in snapshot.items:
        reason = snapshot.inclusion_map.get(item.item_id, "selected")
        preview = redact_secrets(item.content[:240])
        rows.append(
            ContextInspectionRow(
                item_id=item.item_id,
                source=item.source,
                trust_level=item.trust_level,
                token_cost=item.token_cost,
                inclusion_reason=reason,
                provenance=item.provenance,
                content_preview=preview,
            ),
        )
    omitted = [
        {"item_id": o.item_id, "source": o.source, "reason": o.reason, "token_cost": o.token_cost}
        for o in snapshot.omitted_items
    ]
    return {
        "run_id": snapshot.run_id,
        "prompt_hash": snapshot.prompt_hash,
        "assembler_version": snapshot.assembler_version,
        "total_tokens": sum(i.token_cost for i in snapshot.items),
        "budget_input": snapshot.budget.input_budget(),
        "items": [asdict(row) for row in rows],
        "omitted": omitted,
    }
