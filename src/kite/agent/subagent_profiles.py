"""Bundled + user subagent personas — orchestrator picks these over JIT microscopic workers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

from kite.config import ensure_home, kite_home

_FRONTMATTER = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*\n(?P<prompt>.*)$", re.DOTALL)
_FM_LINE = re.compile(r"^([a-z_]+):\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class SubagentProfile:
    id: str
    label: str
    role: str = "auto"
    description: str = ""
    prompt: str = ""

    def compose(self, task: str) -> str:
        task = (task or "").strip()
        header = f"# Subagent: {self.label}\n{self.prompt.strip()}\n\n"
        return f"{header}## Task\n{task}" if task else header.strip()


def _parse_frontmatter(raw: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        m = _FM_LINE.match(line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
    return meta


def _parse_profile_file(path: Path, fallback_id: str) -> SubagentProfile | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None

    meta: dict[str, str] = {}
    prompt = text
    m = _FRONTMATTER.match(text)
    if m:
        meta = _parse_frontmatter(m.group("body"))
        prompt = m.group("prompt").strip()

    pid = meta.get("id") or meta.get("name") or fallback_id
    label = meta.get("label") or pid.replace("-", " ").title()
    return SubagentProfile(
        id=pid.lower(),
        label=label,
        role=(meta.get("role") or "auto").lower(),
        description=meta.get("description") or "",
        prompt=prompt,
    )


def _bundled_dir() -> Path:
    return Path(str(resources.files("kite").joinpath("data/subagents")))


def _user_dir() -> Path:
    ensure_home()
    return kite_home() / "subagents"


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, SubagentProfile]:
    """Bundled profiles first; ~/.kite/subagents/ overrides by id."""
    out: dict[str, SubagentProfile] = {}
    bundled = _bundled_dir()
    if bundled.is_dir():
        for path in sorted(bundled.glob("*.md")):
            prof = _parse_profile_file(path, path.stem)
            if prof:
                out[prof.id] = prof
    user_d = _user_dir()
    if user_d.is_dir():
        for path in sorted(user_d.glob("*.md")):
            prof = _parse_profile_file(path, path.stem)
            if prof:
                out[prof.id] = prof
    return out


def list_profiles() -> list[SubagentProfile]:
    return sorted(load_profiles().values(), key=lambda p: p.id)


def get_profile(profile_id: str) -> SubagentProfile | None:
    key = (profile_id or "").strip().lower()
    if not key:
        return None
    return load_profiles().get(key)


def resolve_subagent_task(
    *,
    prompt: str,
    profile: str = "",
    role: str = "",
    label: str = "",
) -> tuple[str, str, str]:
    """Return (composed_prompt, role, label) for a nested worker."""
    prof = get_profile(profile)
    if prof:
        composed = prof.compose(prompt)
        resolved_role = (role or prof.role or "auto").lower()
        resolved_label = (label or prof.label or prof.id).strip()
        return composed, resolved_role, resolved_label
    resolved_role = (role or "auto").lower()
    resolved_label = (label or prompt[:48].replace("\n", " ")).strip() or "worker"
    return prompt, resolved_role, resolved_label


def profiles_for_orchestrator(*, max_chars: int = 1200) -> str:
    """Catalog of base personas the orchestrator can dispatch anytime."""
    rows = list_profiles()
    if not rows:
        return ""
    lines = [
        "# Base subagent profiles",
        "Prefer these bundled personas over inventing microscopic one-off workers. "
        "Pass `profile` on the subagent tool; add `prompt` for the specific task. "
        "JIT microscopic workers are fine for tiny one-offs.",
        "",
    ]
    for p in rows:
        desc = p.description or p.prompt.split("\n", 1)[0][:120]
        lines.append(f"- **{p.id}** ({p.label}) — role={p.role}: {desc}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n..."
    return text
