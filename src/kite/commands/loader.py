"""Markdown slash commands — Claude-style prompt files, not control-plane builtins."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from kite.config import kite_home

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


@dataclass(frozen=True)
class PromptCommand:
    name: str
    description: str
    body: str
    path: Path
    argument_hint: str = ""
    source: str = "user"  # bundled | user | project | plugin
    plugin: str = ""


def parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("\"'")
    return meta, match.group(2)


def expand_arguments(body: str, arg: str) -> str:
    """Replace $ARGUMENTS / $1..$9 in a command body."""
    text = body.replace("${ARGUMENTS}", arg).replace("$ARGUMENTS", arg).replace("$0", arg)
    parts = arg.split()
    for i, part in enumerate(parts, start=1):
        if i > 9:
            break
        text = text.replace(f"${i}", part)
    return text


def _load_command_file(path: Path, *, source: str, plugin: str = "") -> PromptCommand | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = parse_frontmatter(raw)
    name = (meta.get("name") or path.stem).strip()
    if not NAME_RE.match(name):
        return None
    hint = meta.get("argument-hint") or meta.get("argument_hint") or ""
    desc = meta.get("description") or ""
    content = (body if meta else raw).strip()
    if not content:
        return None
    return PromptCommand(
        name=name.lower(),
        description=desc,
        body=content,
        path=path,
        argument_hint=hint,
        source=source,
        plugin=plugin,
    )


def load_commands_from_dir(
    directory: Path,
    *,
    source: str,
    plugin: str = "",
) -> list[PromptCommand]:
    if not directory.is_dir():
        return []
    out: list[PromptCommand] = []
    for path in sorted(directory.glob("*.md"), key=lambda p: p.name.lower()):
        if path.name.lower() == "readme.md":
            continue
        cmd = _load_command_file(path, source=source, plugin=plugin)
        if cmd is not None:
            out.append(cmd)
    return out


def bundled_commands_dir() -> Path | None:
    try:
        bundled = resources.files("kite").joinpath("data/commands")
        path = Path(str(bundled))
        if path.is_dir():
            return path
    except Exception:
        return None
    return None


def user_commands_dir() -> Path:
    return kite_home() / "commands"


def project_commands_dir(cwd: str | Path) -> Path:
    return Path(cwd).expanduser().resolve() / ".kite" / "commands"


def load_bundled_commands() -> list[PromptCommand]:
    items: list[PromptCommand] = []
    bundled = bundled_commands_dir()
    if bundled is not None:
        items.extend(load_commands_from_dir(bundled, source="bundled"))
    try:
        pkg = resources.files("kite").joinpath("data/commands")
        if hasattr(pkg, "iterdir"):
            seen = {c.name for c in items}
            for child in pkg.iterdir():
                if not child.name.endswith(".md") or child.name.lower() == "readme.md":
                    continue
                stem = child.name[:-3].lower()
                if stem in seen:
                    continue
                raw = child.read_bytes().decode("utf-8")
                meta, body = parse_frontmatter(raw)
                cmd_name = (meta.get("name") or stem).lower()
                if not NAME_RE.match(cmd_name):
                    continue
                items.append(
                    PromptCommand(
                        name=cmd_name,
                        description=meta.get("description") or "",
                        body=(body if meta else raw).strip(),
                        path=Path(str(child)),
                        argument_hint=meta.get("argument-hint") or meta.get("argument_hint") or "",
                        source="bundled",
                    )
                )
                seen.add(cmd_name)
    except Exception:
        pass
    return items


COMMAND_STUB = """\
---
name: {name}
description: Short hint shown in /help
argument-hint:
---

Prompt the agent should follow when the user types `/{name}`.
`$ARGUMENTS` is replaced with whatever they typed after the command.

$ARGUMENTS
"""


def write_command_stub(directory: Path, name: str) -> Path:
    clean = name.strip().lstrip("/").lower()
    if not NAME_RE.match(clean):
        raise ValueError(f"invalid command name '{name}' — use letters, digits, _ or -")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{clean}.md"
    if path.exists():
        raise FileExistsError(str(path))
    path.write_text(COMMAND_STUB.format(name=clean), encoding="utf-8")
    return path
