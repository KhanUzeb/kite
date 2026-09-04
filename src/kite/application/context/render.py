"""Render context items with trust delimiters."""

from __future__ import annotations

from kite.application.context.models import ContextItem, TrustLevel

TRUSTED_LEVELS: frozenset[TrustLevel] = frozenset(
    {
        "trusted_runtime_policy",
        "trusted_user_instruction",
        "trusted_project_instruction",
    },
)

_UNTRUSTED_OPEN = "<!-- kite:untrusted source={source} trust={trust} -->"
_UNTRUSTED_CLOSE = "<!-- /kite:untrusted -->"


def render_item(item: ContextItem) -> str:
    if item.trust_level in TRUSTED_LEVELS:
        return item.content
    open_tag = _UNTRUSTED_OPEN.format(source=item.source, trust=item.trust_level)
    return f"{open_tag}\n{item.content.strip()}\n{_UNTRUSTED_CLOSE}"


def render_snapshot(items: tuple[ContextItem, ...]) -> str:
    sections: list[str] = []
    for item in items:
        rendered = render_item(item)
        if rendered.strip():
            sections.append(rendered)
    return "\n\n".join(sections)
