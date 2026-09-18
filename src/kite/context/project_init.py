"""Scaffold AGENTS.md (agents.md standard) from repo manifests — MiniMax-style bootstrap."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from kite.context.discovery import PROJECT_MARKERS, SKIP_DIRS, find_project_root

_AGENTS_FILENAME = "AGENTS.md"
_KITE_FILENAME = "KITE.md"

_KITE_STUB = """# KITE.md

Project memory for Kite. Read on every session. Keep it short.

## What this repo is

## Conventions

## Do not

"""


@dataclass(frozen=True)
class InitWriteResult:
    path: Path
    action: str  # created | skipped | overwritten
    backup: Path | None = None


@dataclass(frozen=True)
class ProjectInitResult:
    root: Path
    agents: InitWriteResult | None
    kite: InitWriteResult | None


@dataclass(frozen=True)
class EcosystemHints:
    name: str
    install: str
    dev: str | None
    build: str | None
    test: str
    lint: str | None
    typecheck: str | None


def is_git_workspace(root: Path) -> bool:
    return (root / ".git").exists()


def has_root_agents_md(root: Path) -> bool:
    return (root / _AGENTS_FILENAME).is_file()


def needs_agents_bootstrap(root: Path) -> bool:
    """True when this looks like a real project but has no root AGENTS.md."""
    root = root.expanduser().resolve()
    if has_root_agents_md(root):
        return False
    if not is_git_workspace(root):
        return False
    return any((root / marker).exists() for marker in PROJECT_MARKERS)


def bootstrap_nudge_markdown(root: Path) -> str:
    if not needs_agents_bootstrap(root):
        return ""
    dir_s = str(root.expanduser().resolve())
    return (
        "<bootstrap_check>\n"
        f"Your workspace ({dir_s}) has no root AGENTS.md — this project has no "
        "agent-facing setup notes yet.\n\n"
        "Before starting substantive work, ask: would a root AGENTS.md help agents "
        "work on this repo?\n"
        "If yes (git repository with meaningful code), load the `init` skill and follow "
        "it to generate `AGENTS.md` at the repo root, or run `kite init` for a "
        "deterministic scaffold. Let the user review and commit.\n\n"
        "If the repo does not need it (scratch dir, no real code), say so and skip.\n"
        "Do not bootstrap unless the user asks or the skill procedure applies.\n"
        "</bootstrap_check>"
    )


def default_branch(root: Path) -> str:
    for cmd in (
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        ["git", "config", "init.defaultBranch"],
    ):
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        line = (proc.stdout or "").strip()
        if line.startswith("origin/"):
            line = line.split("/", 1)[1]
        if line:
            return line
    return "main"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _one_line_description(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib

            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            desc = (data.get("project") or {}).get("description")
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
        except Exception:
            pass
    pkg = root / "package.json"
    if pkg.is_file():
        desc = _read_json(pkg).get("description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    cargo = root / "Cargo.toml"
    if cargo.is_file():
        for line in cargo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("description"):
                _, _, val = line.partition("=")
                val = val.strip().strip("\"'")
                if val:
                    return val
    readme = root / "README.md"
    if readme.is_file():
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                return text[:200]
            if text.startswith("# "):
                return text[2:].strip()[:200]
    return "Describe what this repository is for."


def _node_pm(root: Path) -> str:
    pkg = root / "package.json"
    if not pkg.is_file():
        return "npm"
    data = _read_json(pkg)
    pm = data.get("packageManager") or ""
    if isinstance(pm, str) and pm.startswith("pnpm"):
        return "pnpm"
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _package_scripts(root: Path) -> dict[str, str]:
    pkg = root / "package.json"
    if not pkg.is_file():
        return {}
    scripts = _read_json(pkg).get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def detect_ecosystem(root: Path) -> EcosystemHints:
    root = root.expanduser().resolve()
    if (root / "pyproject.toml").is_file():
        install = "./scripts/install.sh --dev" if (root / "scripts" / "install.sh").is_file() else "pip install -e '.[dev]'"
        test = "pytest"
        if (root / "scripts" / "ci_check.sh").is_file():
            test = "./scripts/ci_check.sh"
        lint = "ruff check ." if (root / "pyproject.toml").read_text(encoding="utf-8").find("[tool.ruff]") >= 0 else None
        return EcosystemHints(
            name="Python",
            install=install,
            dev=None,
            build=None,
            test=test,
            lint=lint,
            typecheck=None,
        )
    if (root / "package.json").is_file():
        pm = _node_pm(root)
        scripts = _package_scripts(root)
        install = f"{pm} install"
        dev = scripts.get("dev")
        build = scripts.get("build")
        test = scripts.get("test") or f"{pm} test"
        lint = scripts.get("lint")
        typecheck = scripts.get("typecheck")
        return EcosystemHints(
            name="Node.js",
            install=install,
            dev=dev,
            build=build,
            test=test,
            lint=lint,
            typecheck=typecheck,
        )
    if (root / "Cargo.toml").is_file():
        return EcosystemHints(
            name="Rust",
            install="cargo build",
            dev="cargo run",
            build="cargo build --release",
            test="cargo test",
            lint="cargo clippy",
            typecheck=None,
        )
    if (root / "go.mod").is_file():
        return EcosystemHints(
            name="Go",
            install="go mod download",
            dev=None,
            build="go build ./...",
            test="go test ./...",
            lint="go vet ./...",
            typecheck=None,
        )
    return EcosystemHints(
        name="unknown",
        install="<install command>",
        dev=None,
        build=None,
        test="<test command>",
        lint=None,
        typecheck=None,
    )


def _layout_lines(root: Path, *, max_dirs: int = 12) -> list[str]:
    lines: list[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return ["- `(could not list root)`"]
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        if len(lines) >= max_dirs:
            lines.append("- `…` — additional directories omitted")
            break
        lines.append(f"- `{entry.name}/` — ")
    return lines or ["- `(no top-level directories detected)`"]


def render_agents_md(root: Path) -> str:
    root = root.expanduser().resolve()
    eco = detect_ecosystem(root)
    branch = default_branch(root)
    desc = _one_line_description(root)
    layout = "\n".join(_layout_lines(root))

    setup: list[str] = [f"- Install deps: `{eco.install}`"]
    if eco.dev:
        setup.append(f"- Start dev: `{eco.dev}`")
    if eco.build:
        setup.append(f"- Build: `{eco.build}`")
    setup.append(f"- Test: `{eco.test}`")
    if eco.lint:
        setup.append(f"- Lint: `{eco.lint}`")
    if eco.typecheck:
        setup.append(f"- Typecheck: `{eco.typecheck}`")

    security = "- Never commit secrets — keep API keys in user config (e.g. `~/.kite/.env`), not the repo."
    if (root / "SECURITY.md").is_file():
        security += "\n- See `SECURITY.md` for reporting and trust boundaries."

    body = f"""# AGENTS.md

{desc}

## Setup commands

{chr(10).join(setup)}

## Project layout

{layout}

## Testing instructions

- Run `{eco.test}` before opening a PR.
- Add or update tests for behavior changes; follow existing test layout in the repo.

## PR and commit conventions

- Branch from `{branch}`; do not push directly to the default branch.
- Use short conventional commits (`feat:`, `fix:`, `docs:`, …) when the repo already does.
- Run the canonical test command above once changes are ready.

## Security

{security}
"""
    return body.rstrip() + "\n"


def _write_text(
    path: Path,
    content: str,
    *,
    force: bool,
) -> InitWriteResult:
    path = path.expanduser().resolve()
    if path.is_file() and not force:
        return InitWriteResult(path=path, action="skipped", backup=None)
    backup: Path | None = None
    action = "created"
    if path.is_file():
        backup = path.with_name(f"{path.name}.bak.{int(time.time())}")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        action = "overwritten"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return InitWriteResult(path=path, action=action, backup=backup)


def scaffold_project_docs(
    directory: str | Path,
    *,
    write_agents: bool = True,
    write_kite: bool = True,
    force: bool = False,
) -> ProjectInitResult:
    cwd = Path(directory).expanduser().resolve()
    root = find_project_root(cwd)
    agents_result: InitWriteResult | None = None
    kite_result: InitWriteResult | None = None
    if write_agents:
        agents_result = _write_text(
            root / _AGENTS_FILENAME,
            render_agents_md(root),
            force=force,
        )
    if write_kite:
        kite_result = _write_text(root / _KITE_FILENAME, _KITE_STUB, force=force)
    try:
        from kite.context.discovery import invalidate_project_context_cache

        invalidate_project_context_cache()
    except Exception:
        pass
    return ProjectInitResult(root=root, agents=agents_result, kite=kite_result)


def format_init_summary(result: ProjectInitResult) -> str:
    lines: list[str] = [f"project_root: {result.root}"]

    def _row(label: str, wr: InitWriteResult | None) -> None:
        if wr is None:
            return
        extra = f" (backup: {wr.backup})" if wr.backup else ""
        lines.append(f"{label}: {wr.action} → {wr.path}{extra}")

    _row("AGENTS.md", result.agents)
    _row("KITE.md", result.kite)
    return "\n".join(lines)
