"""Bundled + user subagent personas — orchestrator picks these over JIT microscopic workers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

from kite.config import ensure_home, kite_home
from kite.memory.secure_io import wrap_untrusted_user_content

_FRONTMATTER = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*\n(?P<prompt>.*)$", re.DOTALL)
_FM_LINE = re.compile(r"^([a-z_]+):\s*(.+)$", re.IGNORECASE)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_LABEL_RE = re.compile(r"^[\w .:/()-]{1,80}$", re.UNICODE)
_MAX_PROFILE_BYTES = 32_000
_MAX_PROMPT_CHARS = 12_000
_VALID_ROLES = frozenset({"auto", "architect", "implementer", "debugger", "implement", "debug", "plan"})


@dataclass(frozen=True)
class SubagentProfile:
    id: str
    label: str
    role: str = "auto"
    description: str = ""
    prompt: str = ""
    bundled: bool = True

    def compose(self, task: str) -> str:
        task = (task or "").strip()[:4000]
        body = self.prompt.strip()[:_MAX_PROMPT_CHARS]
        if not self.bundled:
            body = wrap_untrusted_user_content(body, source=f"subagent-profile:{self.id}")
        header = f"# Subagent: {self.label}\n{body}\n\n"
        return f"{header}## Task\n{task}" if task else header.strip()


def _parse_frontmatter(raw: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        m = _FM_LINE.match(line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()[:200]
    return meta


def _sanitize_id(raw: str, fallback: str) -> str:
    text = (raw or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9_-]", "-", text).strip("-")
    if not text or not _ID_RE.match(text):
        text = re.sub(r"[^a-z0-9_-]", "-", fallback.lower()).strip("-")[:32]
    return text[:32] or "profile"


def _sanitize_label(raw: str, fallback: str) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", "", (raw or fallback).strip())
    if not text or not _LABEL_RE.match(text):
        text = fallback.replace("-", " ").title()[:80]
    return text[:80]


def _sanitize_role(raw: str) -> str:
    role = (raw or "auto").strip().lower()
    aliases = {"implement": "implementer", "debug": "debugger", "plan": "architect"}
    role = aliases.get(role, role)
    return role if role in _VALID_ROLES else "auto"


def _read_bounded(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        if size > _MAX_PROFILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _safe_user_profile_path(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if not resolved.is_file():
        return None
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved


def _parse_profile_file(path: Path, fallback_id: str, *, bundled: bool) -> SubagentProfile | None:
    text = _read_bounded(path).strip()
    if not text:
        return None

    meta: dict[str, str] = {}
    prompt = text
    m = _FRONTMATTER.match(text)
    if m:
        meta = _parse_frontmatter(m.group("body"))
        prompt = m.group("prompt").strip()

    pid = _sanitize_id(meta.get("id") or meta.get("name") or fallback_id, fallback_id)
    label = _sanitize_label(meta.get("label") or "", pid.replace("-", " ").title())
    return SubagentProfile(
        id=pid,
        label=label,
        role=_sanitize_role(meta.get("role") or "auto"),
        description=(meta.get("description") or "")[:200],
        prompt=prompt[:_MAX_PROMPT_CHARS],
        bundled=bundled,
    )


def _bundled_dir() -> Path:
    return Path(str(resources.files("kite").joinpath("data/subagents")))


def _user_dir() -> Path:
    ensure_home()
    root = kite_home() / "subagents"
    root.mkdir(parents=True, exist_ok=True)
    return root


PROFILE_STUB = """---
id: {id}
label: {label}
role: {role}
description: {description}
---

You are a **{label}** subagent.

Describe what this persona does and how it should behave.

Deliver:
- Clear, scoped output for the assigned task
- File:line references when reviewing or exploring code

Prefer read-only tools unless the task explicitly requires edits.
"""


def user_profiles_dir() -> Path:
    return _user_dir()


def user_profile_path(profile_id: str) -> Path:
    pid = _sanitize_id(profile_id, profile_id)
    return user_profiles_dir() / f"{pid}.md"


def format_profile_trust(profile: SubagentProfile) -> str:
    return "bundled" if profile.bundled else "user-local"


def init_user_profile(
    profile_id: str,
    *,
    label: str = "",
    role: str = "auto",
    description: str = "",
    force: bool = False,
) -> Path:
    """Write ~/.kite/subagents/<id>.md stub; returns path."""
    raw = (profile_id or "").strip().lower()
    if not raw or not _ID_RE.match(raw):
        raise ValueError(f"invalid profile id '{profile_id}' — use a-z, 0-9, _, - (max 32)")
    pid = raw
    path = user_profile_path(pid)
    if path.is_file() and not force:
        raise FileExistsError(str(path))
    resolved_label = _sanitize_label(label, pid.replace("-", " ").title())
    resolved_role = _sanitize_role(role)
    desc = (description or f"Custom {resolved_label} subagent persona.")[:200]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        PROFILE_STUB.format(
            id=pid,
            label=resolved_label,
            role=resolved_role,
            description=desc,
        ),
        encoding="utf-8",
    )
    reload_profiles()
    return path


def profile_source_path(profile: SubagentProfile) -> Path | None:
    """Best-effort path for display — bundled or user file."""
    if profile.bundled:
        candidate = _bundled_dir() / f"{profile.id}.md"
        return candidate if candidate.is_file() else None
    candidate = user_profile_path(profile.id)
    safe = _safe_user_profile_path(candidate, user_profiles_dir())
    return safe


def reload_profiles() -> None:
    load_profiles.cache_clear()


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, SubagentProfile]:
    """Bundled profiles first; ~/.kite/subagents/ overrides by id."""
    out: dict[str, SubagentProfile] = {}
    bundled = _bundled_dir()
    if bundled.is_dir():
        for path in sorted(bundled.glob("*.md")):
            prof = _parse_profile_file(path, path.stem, bundled=True)
            if prof:
                out[prof.id] = prof
    user_d = _user_dir()
    if user_d.is_dir():
        for path in sorted(user_d.glob("*.md")):
            safe = _safe_user_profile_path(path, user_d)
            if safe is None:
                continue
            prof = _parse_profile_file(safe, safe.stem, bundled=False)
            if prof:
                out[prof.id] = prof
    return out


def list_profiles() -> list[SubagentProfile]:
    return sorted(load_profiles().values(), key=lambda p: p.id)


def get_profile(profile_id: str) -> SubagentProfile | None:
    raw = (profile_id or "").strip().lower()
    if not raw:
        return None
    key = _sanitize_id(raw, raw)
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
    safe_prompt = (prompt or "").strip()[:4000]
    if prof:
        composed = prof.compose(safe_prompt)
        resolved_role = _sanitize_role(role or prof.role)
        resolved_label = _sanitize_label(label or prof.label, prof.id)
        return composed, resolved_role, resolved_label
    resolved_role = _sanitize_role(role)
    resolved_label = _sanitize_label(label, safe_prompt[:48].replace("\n", " ") or "worker")
    return safe_prompt, resolved_role, resolved_label


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
        trust = "bundled" if p.bundled else "user-local"
        lines.append(f"- **{p.id}** ({p.label}) — role={p.role}, trust={trust}: {desc}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n..."
    return text
