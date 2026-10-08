"""Evidence-based verification plans and workspace profiles."""

from __future__ import annotations

import hashlib
import html.parser
import json
import re
import tomllib
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from kite.application.tools import ToolResult
from kite.context.discovery import SKIP_DIRS

PACKAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml", "setup.py", "setup.cfg"),
    "js": ("package.json",),
    "rust": ("Cargo.toml",),
    "go": ("go.mod",),
}

_PYTHON_TEST_SUFFIXES = ("_test.py", "test_.py")
_MAX_SCAN_DEPTH = 8
_MAX_PACKAGES = 64


@dataclass(frozen=True, slots=True)
class PackageUnit:
    """One buildable unit inside a workspace (app, service, crate, module)."""

    key: str
    root: str
    ecosystems: frozenset[str]
    test_command: str | None = None
    lint_command: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceProfile:
    """Discovered verification context for a workspace — not a single-repo assumption."""

    workspace_root: str
    packages: tuple[PackageUnit, ...] = ()
    workspace_commands: tuple[str, ...] = ()

    def package_for(self, relative_path: str) -> PackageUnit | None:
        norm = PurePosixPath(relative_path.replace("\\", "/"))
        best: PackageUnit | None = None
        best_len = -1
        for pkg in self.packages:
            prefix = PurePosixPath(pkg.root.replace("\\", "/"))
            if prefix == norm or prefix in norm.parents:
                if len(prefix.parts) > best_len:
                    best = pkg
                    best_len = len(prefix.parts)
        return best

    def scoped_test_command(self, relative_path: str) -> str | None:
        pkg = self.package_for(relative_path)
        if pkg and pkg.test_command:
            return pkg.test_command
        return None


def normalize_workspace_path(path: str, workspace_root: str | Path | None) -> str:
    """Return a workspace-relative POSIX path when the path is inside the workspace."""
    raw = str(path or "").strip()
    if not raw:
        return ""
    if not workspace_root:
        return raw.replace("\\", "/")

    root = Path(workspace_root).expanduser().resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        return resolved.relative_to(root).as_posix()
    except (OSError, ValueError):
        return candidate.absolute().as_posix()




def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _ecosystems_at(directory: Path) -> frozenset[str]:
    found: set[str] = set()
    for eco, markers in PACKAGE_MARKERS.items():
        if any(_is_file(directory / marker) for marker in markers):
            found.add(eco)
    return frozenset(found)


def _load_user_profile(workspace: Path) -> tuple[tuple[str, ...], dict[str, dict[str, str]]]:
    cfg_path = workspace / ".kite" / "verification.toml"
    raw = _read_toml(cfg_path)
    workspace_commands = tuple(str(c) for c in raw.get("commands", ()) if c)
    packages: dict[str, dict[str, str]] = {}
    pkg_table = raw.get("packages", {})
    if isinstance(pkg_table, dict):
        for key, entry in pkg_table.items():
            if isinstance(entry, dict):
                packages[str(key)] = {str(k): str(v) for k, v in entry.items() if v}
    return workspace_commands, packages


def _default_js_test(directory: Path) -> str | None:
    pkg = directory / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return None
    for name in ("test", "test:unit", "check", "verify", "lint"):
        cmd = scripts.get(name)
        if isinstance(cmd, str) and cmd.strip():
            if name == "lint":
                return None
            return f"npm run {name}" if name != "test" else "npm test"
    return None


def _default_python_test(directory: Path, workspace: Path) -> str | None:
    if (directory / "pytest.ini").is_file():
        return "pytest -q"
    pyproject = directory / "pyproject.toml"
    if pyproject.is_file():
        data = _read_toml(pyproject)
        if "pytest" in data.get("tool", {}) or "pytest.ini_options" in data.get("tool", {}):
            return "pytest -q"
        scripts = data.get("project", {}).get("scripts", {})
        if isinstance(scripts, dict):
            for name in ("test", "pytest"):
                if name in scripts:
                    return "pytest -q"
    if (directory / "tox.ini").is_file():
        return "tox -q"
    if (directory / "Makefile").is_file():
        try:
            text = (directory / "Makefile").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("test:") or stripped == "test":
                return "make test"
    return None


def _infer_python_test_targets(pkg_root: Path, workspace: Path, touched: str) -> tuple[str, ...]:
    rel = PurePosixPath(touched.replace("\\", "/"))
    stem = rel.stem
    parent = rel.parent
    candidates: list[str] = [
        f"tests/test_{stem}.py",
        f"test/test_{stem}.py",
        f"tests/{stem}_test.py",
    ]
    if parent.parts:
        candidates.append(f"{parent}/test_{stem}.py")
        candidates.append(f"{parent}/tests/test_{stem}.py")
    parts = rel.parts
    if "src" in parts:
        idx = parts.index("src")
        tail = parts[idx + 1 :]
        if tail:
            mod = "/".join(tail)
            candidates.append(f"tests/test_{tail[-1]}")
            candidates.append(f"tests/{mod.replace('.py', '_test.py')}")
    found: list[str] = []
    for candidate in candidates:
        if (pkg_root / candidate).is_file():
            found.append(candidate)
    if found:
        return tuple(dict.fromkeys(found))[:6]
    if touched.endswith(_PYTHON_TEST_SUFFIXES) or "/tests/" in touched.replace("\\", "/"):
        return (touched,)
    return ()


def _python_command_for_paths(
    workspace: Path,
    pkg: PackageUnit,
    paths: tuple[str, ...],
) -> str:
    if pkg.test_command:
        return pkg.test_command
    pkg_root = workspace / pkg.root
    targets: list[str] = []
    for path in paths:
        targets.extend(_infer_python_test_targets(pkg_root, workspace, path))
    unique = list(dict.fromkeys(targets))[:8]
    if unique:
        rel_targets = [f"{pkg.root}/{t}" if pkg.root else t for t in unique]
        return f"pytest -q {' '.join(rel_targets)}"
    default = _default_python_test(pkg_root, workspace)
    if default:
        return default if not pkg.root else f"cd {pkg.root} && {default}"
    compile_paths = " ".join(paths[:8])
    return f"python -m py_compile {compile_paths}"


def _scan_packages(workspace: Path, user_packages: dict[str, dict[str, str]]) -> list[PackageUnit]:
    found: list[PackageUnit] = []
    queue: list[tuple[Path, int]] = [(workspace, 0)]
    seen_roots: set[Path] = set()

    while queue and len(found) < _MAX_PACKAGES:
        directory, depth = queue.pop(0)
        if depth > _MAX_SCAN_DEPTH:
            continue
        ecosystems = _ecosystems_at(directory)
        if ecosystems:
            rel = directory.relative_to(workspace).as_posix() if directory != workspace else ""
            key = rel or "."
            user = user_packages.get(key) or user_packages.get(rel) or {}
            user_test = user.get("test") or user.get("verify")
            test_cmd = user_test
            lint_cmd = user.get("lint")
            if not test_cmd:
                if "python" in ecosystems:
                    test_cmd = _default_python_test(directory, workspace)
                elif "js" in ecosystems:
                    test_cmd = _default_js_test(directory)
                elif "rust" in ecosystems:
                    test_cmd = "cargo test"
                elif "go" in ecosystems:
                    test_cmd = "go test ./..."
                if test_cmd and rel:
                    test_cmd = f"cd {rel} && {test_cmd}"
            found.append(
                PackageUnit(
                    key=key,
                    root=rel,
                    ecosystems=ecosystems,
                    test_command=test_cmd,
                    lint_command=lint_cmd,
                )
            )
            try:
                seen_roots.add(directory.resolve())
            except OSError:
                pass
        if depth >= _MAX_SCAN_DEPTH:
            continue
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if not _is_dir(entry) or entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            try:
                resolved = entry.resolve()
            except OSError:
                continue
            if resolved in seen_roots:
                continue
            queue.append((entry, depth + 1))
    found.sort(key=lambda p: len(p.root))
    return found


def discover_workspace_profile(workspace_root: str | Path) -> WorkspaceProfile:
    """Discover packages and verification commands for any workspace layout."""
    workspace = Path(workspace_root).expanduser().resolve()
    workspace_commands, user_packages = _load_user_profile(workspace)
    if not workspace_commands:
        from kite.context.verify_hint import resolve_verification_command

        cmd, _src = resolve_verification_command(workspace)
        if cmd:
            workspace_commands = (cmd,)
    packages = tuple(_scan_packages(workspace, user_packages))
    return WorkspaceProfile(
        workspace_root=str(workspace),
        packages=packages,
        workspace_commands=workspace_commands,
    )


def group_paths_by_package(
    paths: tuple[str, ...],
    profile: WorkspaceProfile,
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for path in paths:
        pkg = profile.package_for(path)
        key = pkg.key if pkg else "."
        grouped.setdefault(key, []).append(path)
    return {k: tuple(v) for k, v in grouped.items()}




ArtifactKind = Literal["python", "html", "js", "css", "config", "docs", "rust", "go", "other"]
CheckKind = Literal["parser", "project_test", "lint", "syntax", "structural"]
Platform = Literal["windows", "posix", "any"]
VerificationTerminal = Literal[
    "verified", "partial", "changed_unverified", "failed", "blocked", "idle"
]


@dataclass(frozen=True, slots=True)
class CheckSpec:
    kind: CheckKind
    command: str | None
    affected_paths: tuple[str, ...]
    platform: Platform = "any"
    artifact_kind: ArtifactKind = "other"
    package_root: str = ""


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    check: CheckSpec
    command: str
    affected_paths: tuple[str, ...]
    exit_status: int | None
    ok: bool
    output_summary: str
    satisfies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerificationPlan:
    touched_paths: tuple[str, ...]
    artifact_kinds: frozenset[ArtifactKind]
    required_checks: tuple[CheckSpec, ...]
    optional_checks: tuple[CheckSpec, ...] = ()
    workspace_root: str = ""
    package_count: int = 0

    @property
    def has_required_checks(self) -> bool:
        return bool(self.required_checks)


def classify_path(path: str) -> ArtifactKind:
    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    if suffix in {".py", ".pyi"}:
        return "python"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return "js"
    if suffix in {".css", ".scss", ".less"}:
        return "css"
    if suffix in {".rs"}:
        return "rust"
    if suffix in {".go"}:
        return "go"
    if suffix in {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"}:
        return "config"
    if suffix in {".md", ".rst", ".txt"}:
        return "docs"
    return "other"


def classify_touched_paths(paths: tuple[str, ...] | list[str]) -> frozenset[ArtifactKind]:
    return frozenset(classify_path(p) for p in paths if p)


def _python_checks(
    paths: tuple[str, ...],
    profile: WorkspaceProfile | None,
) -> tuple[CheckSpec, ...]:
    py_paths = tuple(p for p in paths if classify_path(p) == "python")
    if not py_paths:
        return ()
    if profile is None:
        return (
            CheckSpec(
                kind="lint",
                command=f"python -m py_compile {' '.join(py_paths[:8])}" if py_paths else None,
                affected_paths=py_paths,
                artifact_kind="python",
            ),
        )
    checks: list[CheckSpec] = []
    grouped = group_paths_by_package(py_paths, profile)
    workspace = profile.workspace_root
    for pkg_key, pkg_paths in grouped.items():
        unit = next((p for p in profile.packages if p.key == pkg_key), None)
        if unit is None:
            cmd = f"python -m py_compile {' '.join(pkg_paths[:8])}"
            checks.append(
                CheckSpec(
                    kind="lint",
                    command=cmd,
                    affected_paths=pkg_paths,
                    artifact_kind="python",
                    package_root=pkg_key if pkg_key != "." else "",
                )
            )
            continue
        cmd = _python_command_for_paths(Path(workspace), unit, pkg_paths)
        checks.append(
            CheckSpec(
                kind="project_test",
                command=cmd,
                affected_paths=pkg_paths,
                artifact_kind="python",
                package_root=unit.root,
            )
        )
    return tuple(checks)


def _html_checks(paths: tuple[str, ...]) -> tuple[CheckSpec, ...]:
    html_paths = tuple(p for p in paths if classify_path(p) == "html")
    if not html_paths:
        return ()
    return (
        CheckSpec(
            kind="structural",
            command=None,
            affected_paths=html_paths,
            artifact_kind="html",
        ),
    )


def _js_checks(
    paths: tuple[str, ...],
    profile: WorkspaceProfile | None,
) -> tuple[CheckSpec, ...]:
    js_paths = tuple(p for p in paths if classify_path(p) == "js")
    if not js_paths:
        return ()
    if profile:
        checks: list[CheckSpec] = []
        for pkg_key, pkg_paths in group_paths_by_package(js_paths, profile).items():
            unit = next((p for p in profile.packages if p.key == pkg_key), None)
            cmd = unit.test_command if unit and unit.test_command else f"node --check {pkg_paths[0]}"
            checks.append(
                CheckSpec(
                    kind="syntax",
                    command=cmd,
                    affected_paths=pkg_paths,
                    artifact_kind="js",
                    package_root=unit.root if unit else "",
                )
            )
        return tuple(checks)
    return (
        CheckSpec(
            kind="syntax",
            command=f"node --check {js_paths[0]}",
            affected_paths=js_paths,
            artifact_kind="js",
        ),
    )


def _rust_checks(
    paths: tuple[str, ...],
    profile: WorkspaceProfile | None,
) -> tuple[CheckSpec, ...]:
    rust_paths = tuple(p for p in paths if classify_path(p) == "rust")
    if not rust_paths:
        return ()
    if profile:
        checks: list[CheckSpec] = []
        for pkg_key, pkg_paths in group_paths_by_package(rust_paths, profile).items():
            unit = next((p for p in profile.packages if p.key == pkg_key), None)
            cmd = unit.test_command if unit and unit.test_command else "cargo test"
            checks.append(
                CheckSpec(
                    kind="project_test",
                    command=cmd,
                    affected_paths=pkg_paths,
                    artifact_kind="rust",
                    package_root=unit.root if unit else "",
                )
            )
        return tuple(checks)
    return (
        CheckSpec(
            kind="project_test",
            command="cargo test",
            affected_paths=rust_paths,
            artifact_kind="rust",
        ),
    )


def _go_checks(
    paths: tuple[str, ...],
    profile: WorkspaceProfile | None,
) -> tuple[CheckSpec, ...]:
    go_paths = tuple(p for p in paths if classify_path(p) == "go")
    if not go_paths:
        return ()
    if profile:
        checks: list[CheckSpec] = []
        for pkg_key, pkg_paths in group_paths_by_package(go_paths, profile).items():
            unit = next((p for p in profile.packages if p.key == pkg_key), None)
            cmd = unit.test_command if unit and unit.test_command else "go test ./..."
            checks.append(
                CheckSpec(
                    kind="project_test",
                    command=cmd,
                    affected_paths=pkg_paths,
                    artifact_kind="go",
                    package_root=unit.root if unit else "",
                )
            )
        return tuple(checks)
    return (
        CheckSpec(
            kind="project_test",
            command="go test ./...",
            affected_paths=go_paths,
            artifact_kind="go",
        ),
    )


def build_verification_plan(
    touched_paths: tuple[str, ...] | list[str],
    *,
    profile: WorkspaceProfile | None = None,
) -> VerificationPlan:
    """Select checks from touched paths and workspace layout — monorepo-aware."""
    workspace_root = profile.workspace_root if profile else None
    paths = tuple(
        normalize_workspace_path(path, workspace_root)
        for path in touched_paths
        if path
    )
    kinds = classify_touched_paths(paths)
    required: list[CheckSpec] = []
    optional: list[CheckSpec] = []

    if "python" in kinds:
        required.extend(_python_checks(paths, profile))
    if "html" in kinds:
        # Simple markup has no runnable check — the structural parse is
        # recorded automatically on write and stays advisory only, so plain
        # .html edits submit freely like docs.
        optional.extend(_html_checks(paths))
    if "js" in kinds:
        required.extend(_js_checks(paths, profile))
    if "rust" in kinds:
        required.extend(_rust_checks(paths, profile))
    if "go" in kinds:
        required.extend(_go_checks(paths, profile))
    if "config" in kinds:
        cfg_paths = tuple(p for p in paths if classify_path(p) == "config")
        optional.append(
            CheckSpec(kind="parser", command=None, affected_paths=cfg_paths, artifact_kind="config")
        )
    if profile and profile.workspace_commands:
        optional.append(
            CheckSpec(
                kind="project_test",
                command=profile.workspace_commands[0],
                affected_paths=paths,
                artifact_kind="other",
                package_root=".",
            )
        )

    package_count = len(profile.packages) if profile else 0
    return VerificationPlan(
        touched_paths=paths,
        artifact_kinds=kinds,
        required_checks=tuple(required),
        optional_checks=tuple(optional),
        workspace_root=profile.workspace_root if profile else "",
        package_count=package_count,
    )


def record_satisfies_check(record: VerificationRecord, check: CheckSpec) -> bool:
    """True when a verification record satisfies the given check for its artifact kind."""
    if not record.ok:
        return False
    if record.check.artifact_kind != check.artifact_kind:
        return False
    record_paths = set(record.affected_paths)
    check_paths = set(check.affected_paths)
    if check_paths and not record_paths.intersection(check_paths):
        return False
    if check.package_root and record.check.package_root and check.package_root != record.check.package_root:
        return False
    if check.command and record.command:
        return check.kind == record.check.kind
    return record.check.kind == check.kind


def plan_status(
    plan: VerificationPlan,
    records: list[VerificationRecord],
) -> VerificationTerminal:
    if not plan.touched_paths:
        return "idle"
    if not plan.required_checks:
        return "changed_unverified"
    satisfied = 0
    failed = 0
    for check in plan.required_checks:
        matching = [r for r in records if record_satisfies_check(r, check)]
        if any(r.ok for r in matching):
            satisfied += 1
        elif matching:
            failed += 1
    if failed:
        return "failed"
    if satisfied == len(plan.required_checks):
        return "verified"
    if satisfied:
        return "partial"
    return "changed_unverified"


def plan_summary(plan: VerificationPlan, records: list[VerificationRecord]) -> dict[str, Any]:
    status = plan_status(plan, records)
    return {
        "status": status,
        "touched_paths": list(plan.touched_paths),
        "artifact_kinds": sorted(plan.artifact_kinds),
        "required_checks": len(plan.required_checks),
        "records": len(records),
        "workspace_root": plan.workspace_root,
        "package_count": plan.package_count,
    }




EvidenceStatus = Literal["passed", "failed", "partial", "unverified"]


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    run_id: str
    tool_call_id: str
    command: str
    normalized_command: str
    cwd: str
    exit_code: int
    duration: float
    stdout_digest: str
    stderr_digest: str
    scope: str
    status: EvidenceStatus


_TEST_HINTS = (
    "pytest",
    "python -m pytest",
    "npm test",
    "go test",
    "cargo test",
    "ruff check",
    "mypy",
    "py_compile",
    "node --check",
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _normalize_command(cmd: str) -> str:
    return re.sub(r"\s+", " ", cmd.strip().lower())


def normalize_check_command(cmd: str) -> str:
    """Whitespace/case-folded command key — pairs repeat runs with their failure."""
    return _normalize_command(cmd)


def is_check_command(command: str) -> bool:
    norm = _normalize_command(command)
    return any(h in norm for h in _TEST_HINTS)


@dataclass
class EvidenceVerifier:
    """Derive verification only from tool results — not model claims."""

    run_id: str
    records: list[EvidenceRecord] = field(default_factory=list)
    changed_hashes: dict[str, str] = field(default_factory=dict)

    def consume(self, result: ToolResult, *, command: str = "", cwd: str = "") -> EvidenceRecord | None:
        cmd = command or str(result.metadata.get("command", ""))
        if not cmd and result.output:
            cmd = result.output.split("\n", 1)[0][:200]
        if not cmd or not is_check_command(cmd):
            return None
        norm = _normalize_command(cmd)
        exit_code = int(result.metadata.get("exit_code", 0 if result.ok else 1))
        status: EvidenceStatus = "passed" if result.ok and exit_code == 0 else "failed"
        record = EvidenceRecord(
            evidence_id=str(uuid.uuid4()),
            run_id=self.run_id,
            tool_call_id=result.call_id,
            command=cmd,
            normalized_command=norm,
            cwd=cwd,
            exit_code=exit_code,
            duration=result.duration,
            stdout_digest=_digest(result.output),
            stderr_digest=_digest(result.error),
            scope="test",
            status=status,
        )
        self.records.append(record)
        return record

    def record_file_hash(self, path: str, content: bytes) -> None:
        self.changed_hashes[path] = hashlib.sha256(content).hexdigest()

    def verification_status(self) -> dict[str, Any]:
        passed = [r for r in self.records if r.status == "passed"]
        failed = [r for r in self.records if r.status == "failed"]
        if passed and not failed:
            status = "verified"
        elif passed and failed:
            status = "partial"
        elif failed:
            status = "failed"
        else:
            status = "unverified"
        return {
            "status": status,
            "evidence_count": len(self.records),
            "passed": len(passed),
            "failed": len(failed),
            "records": [asdict(r) for r in self.records],
            "changed_hashes": self.changed_hashes,
        }

    def model_claim_satisfies(self, claim: str) -> bool:
        """Model-written claims cannot satisfy verification without evidence."""
        if not self.records:
            return False
        if "test" in claim.lower() and "pass" in claim.lower():
            return any(r.status == "passed" for r in self.records)
        return False




if TYPE_CHECKING:
    from kite.agent.verification import Artifact, VerificationCollector, VerificationStatus

_TEST_HINTS = (
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "npm test",
    "pnpm test",
    "yarn test",
    "go test",
    "cargo test",
    "bazel test",
    "nx test",
    "make test",
    "ruff check",
    "mypy",
    "uv run pytest",
    "uv run ruff",
    "py_compile",
    "node --check",
)
_TEST_GAP_PREFIX = "test command failed"

# A failing check is not always a code defect. Knowing *which* kind of failure it
# is decides block-vs-disclose: a missing runner or a timeout can never be fixed
# by retrying, so blocking on it only burns the step and token budget.
FailureClass = Literal["assertion", "collection", "runner_missing", "timeout", "environment"]
UNFIXABLE_FAILURE_CLASSES: frozenset[str] = frozenset({"runner_missing", "timeout", "environment"})

# How many times one submit may be blocked before the run stops instead of
# retrying. The first blocks explain; the last one ends the run with the report.
MAX_BLOCKED_SUBMITS = 3

_RUNNER_MISSING_RE = re.compile(
    r"(command not found"
    r"|is not recognized as an internal or external command"
    r"|no module named"
    r"|module not found"
    r"|unable to locate program"
    r"|cannot find the path specified"
    r"|executable file not found"
    r"|no such file or directory: ['\"]?(pytest|npm|node|go|cargo|tox))",
    re.IGNORECASE,
)
_TIMEOUT_RE = re.compile(r"(timed out|timeout|test timeout)", re.IGNORECASE)
_ENVIRONMENT_RE = re.compile(
    r"(permission denied|read-only file system|connection refused"
    r"|network is unreachable|operation not permitted|device or resource busy)",
    re.IGNORECASE,
)
_COLLECTION_RE = re.compile(
    r"(importerror|modulenotfounderror|syntaxerror"
    r"|importerror while importing"
    r"|errors? (on|during) collection"
    r"|error collecting)",
    re.IGNORECASE,
)


def classify_failure(exit_code: int, output: str = "", error: str = "") -> FailureClass:
    """Name the kind of failure a check produced."""
    text = f"{output}\n{error}"
    if exit_code in {127, 9009} or _RUNNER_MISSING_RE.search(text):
        return "runner_missing"
    if _TIMEOUT_RE.search(text):
        return "timeout"
    if _ENVIRONMENT_RE.search(text):
        return "environment"
    if _COLLECTION_RE.search(text):
        return "collection"
    return "assertion"


@dataclass(frozen=True, slots=True)
class CheckFailure:
    """One failed verification check and why it failed."""

    command: str = ""
    exit_code: int | None = None
    kind: str = "check"
    failure_class: FailureClass = "assertion"
    detail: str = ""

    @property
    def unfixable(self) -> bool:
        """True when no amount of retrying can turn this check green."""
        return self.failure_class in UNFIXABLE_FAILURE_CLASSES

    @property
    def text(self) -> str:
        if self.command:
            return f"{_TEST_GAP_PREFIX} (exit {self.exit_code}): {self.command[:80]}"
        return self.detail or "verification check failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command[:80],
            "exit_code": self.exit_code,
            "kind": self.kind,
            "failure_class": self.failure_class,
            "unfixable": self.unfixable,
        }


# Honest spellings the gate accepts instead of a green check: a report that says
# what is broken is worth more than a loop that retries a command already known
# to fail. `- ✗` marks a failed check; a `## Blocked` section names the blockers.
_FAILED_MARKER_RE = re.compile(r"^\s*[-*]\s*[✗✘]", re.MULTILINE)
_BLOCKED_SECTION_RE = re.compile(
    r"^#{2,4}\s*(blocked|blocking|known\s+issues|not\s+verified|unverified|could\s+not\s+verify)",
    re.IGNORECASE | re.MULTILINE,
)


def discloses_failures(body: str) -> bool:
    """True when a summary states its failures outright instead of claiming success."""
    text = body or ""
    if not text.strip():
        return False
    return bool(_FAILED_MARKER_RE.search(text) or _BLOCKED_SECTION_RE.search(text))


_EVIDENCE_CLAIM_RE = re.compile(
    r"\b("
    r"tests?\s+pass(?:ed|ing)?|all\s+tests?\s+pass|"
    r"build\s+succeeds?|lint\s+clean|no\s+errors?|"
    r"fully\s+verified|confirmed\s+working|everything\s+works"
    r")\b",
    re.IGNORECASE,
)
_DONE_CLAIM_RE = re.compile(
    r"\b("
    r"task\s+complete|i(?:'ve| have)?\s+finished|"
    r"should\s+(?:work|pass)|looks\s+(?:good|fine)|"
    r"we(?:'re| are)\s+done|successfully\s+(?:implemented|fixed|completed)|"
    r"fully\s+implemented|all\s+good"
    r")\b",
    re.IGNORECASE,
)


class _HtmlChecker(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parse_error: str | None = None

    def error(self, message: str) -> None:  # type: ignore[override]
        self.parse_error = message


def html_parse_ok(content: str) -> bool:
    if not content.strip():
        return True
    checker = _HtmlChecker()
    try:
        checker.feed(content)
        checker.close()
    except Exception:
        return False
    if checker.parse_error is not None:
        return False
    lowered = content.lower()
    if "<html" in lowered and "</html>" not in lowered:
        return False
    return True


def looks_like_test(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(h in lowered for h in _TEST_HINTS)


def latest_test(artifacts: list[Artifact]) -> Artifact | None:
    tests = [a for a in artifacts if a.kind == "test"]
    return tests[-1] if tests else None


def terminal_status(collector: VerificationCollector) -> VerificationStatus:
    latest = latest_test(collector.artifacts)
    if latest is not None and not latest.ok:
        return "failed"
    if collector.gaps:
        return "failed"
    if not collector.has_edits() and not collector.paths_touched:
        if latest is not None and latest.ok:
            return "verified"
        if collector.artifacts:
            return (
                "partial"
                if any(a.kind == "command" and a.ok for a in collector.artifacts)
                else "unverified"
            )
        return "idle"
    plan = collector.plan()
    st = plan_status(plan, collector._records)
    if st == "changed_unverified" and collector.has_edits():
        return "changed_unverified"
    return st  # type: ignore[return-value]


def record_html_check(collector: VerificationCollector, path: str, content: str) -> None:
    plan = collector.plan()
    material = (content or "").strip()
    if not material:
        return
    for check in plan.required_checks:
        if check.artifact_kind != "html" or path not in check.affected_paths:
            continue
        ok = html_parse_ok(material)
        collector._records.append(
            VerificationRecord(
                check=check,
                command="html-parse",
                affected_paths=(path,),
                exit_status=0 if ok else 1,
                ok=ok,
                output_summary="structural parse ok" if ok else "html parse failed",
                satisfies=(path,) if ok else (),
            )
        )
        return


def _match_bash_check(cmd: str, plan) -> CheckSpec | None:
    lowered = cmd.lower()
    for check in plan.required_checks:
        if check.command and check.command.lower() in lowered:
            return check
        if check.artifact_kind == "python" and "pytest" in lowered:
            return check
        if check.artifact_kind == "js" and ("npm test" in lowered or "pnpm test" in lowered or "yarn test" in lowered):
            return check
        if check.artifact_kind == "rust" and "cargo test" in lowered:
            return check
        if check.artifact_kind == "go" and "go test" in lowered:
            return check
        if check.artifact_kind == "js" and "node --check" in lowered:
            return check
    return None


#: Suffixes that make a bare token a specific file in a check command.
_FILE_EXTS = (
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".rs", ".go", ".html", ".css",
)

#: Shell control operators. A command built from these cannot be read as a plain
#: argument list — `cd pkg && pytest -q` (which the planner itself emits) moves
#: the base directory mid-command — so its scope is left alone. `&` covers
#: backgrounding, `<` input redirection, `>` output redirection.
_SHELL_OPS = ("&&", "||", ";", "|", "`", "$(", ">", "<", "&")


def _file_targets(cmd: str) -> tuple[str, ...]:
    """Tokens naming a specific file — `tests/test_a.py` as much as `test_a.py`.

    Only a known file suffix qualifies. A bare directory (`docs`) or a flag value
    is deliberately dropped: it cannot prove what was skipped, and guessing at it
    would narrow evidence on a misreading. Glob tokens (`tests/*.py`) are also
    dropped: they name a set, not a file, and treating the pattern as one file
    would narrow coverage to nothing. When any token is dropped the command
    may still be whole-package, so nothing is narrowed (see `_covered_paths`).
    """
    targets: list[str] = []
    for raw in (cmd or "").split():
        token = raw.strip("'\"").rstrip(",")
        if token.startswith("-"):
            continue
        if "*" in token or "?" in token or "[" in token:
            continue
        if token.lower().endswith(_FILE_EXTS):
            targets.append(token)
    return tuple(targets)


def _runs_the_edit(affected: str, target: str, pkg_root: Path) -> bool:
    """Whether running `target` exercises the edited `affected` file."""
    rel = affected.replace("\\", "/")
    name = PurePosixPath(rel).name
    norm = target.replace("\\", "/")
    # Running the edited file itself is the most direct evidence there is.
    if norm in {rel, name}:
        return True
    # A relative test path that ends at the edited file's name (`src/../tests/
    # test_app.py` aside) is still that file's own test.
    if norm.endswith("/" + name):
        return True
    # The planner derives these test files from the edited path, so running one
    # is evidence for that path; running some other test file is not.
    return norm in _infer_python_test_targets(pkg_root, pkg_root, rel)


def _covered_paths(check: CheckSpec, cmd: str, workspace_root: str) -> tuple[str, ...]:
    """Paths this command really covered: the check's, minus what it skipped.

    A record that inherits its check's paths wholesale makes the path
    intersection in `record_satisfies_check` vacuous, which is how a green run
    of an unrelated test file ends up vouching for a file it never touched.

    Only a provable exclusion narrows anything: a command must be a plain
    argument list that names at least one specific file, and every one of those
    files must be unrelated to the edited path. Anything ambiguous keeps full
    coverage, so this can only ever hold the gate to a higher bar than before.
    """
    cmd = cmd or ""
    if not workspace_root or any(op in cmd for op in _SHELL_OPS):
        return check.affected_paths
    targets = _file_targets(cmd)
    if not targets:
        return check.affected_paths
    pkg_root = Path(workspace_root)
    if check.package_root:
        pkg_root = pkg_root / check.package_root
    return tuple(
        path
        for path in check.affected_paths
        if any(_runs_the_edit(path, target, pkg_root) for target in targets)
    )


def record_bash_check(
    collector: VerificationCollector,
    cmd: str,
    *,
    ok: bool,
    exit_code: int,
    preview: str,
    add_artifact: Any,
    output: str = "",
) -> None:
    if not looks_like_test(cmd):
        return
    plan = collector.plan()
    matched = _match_bash_check(cmd, plan)
    covered = _covered_paths(matched, cmd, collector.workspace_root) if matched else ()
    record = VerificationRecord(
        check=matched
        or CheckSpec(kind="project_test", command=cmd, affected_paths=(), artifact_kind="python"),
        command=cmd,
        affected_paths=covered,
        exit_status=exit_code,
        ok=ok and exit_code == 0,
        output_summary=preview,
        satisfies=covered,
    )
    collector._records.append(record)
    add_artifact("test", f"exit={exit_code}  {cmd[:80]}", ok=record.ok, detail=preview)
    if record.ok:
        collector.clear_failure(cmd)
    else:
        # Classify from the full output, not the 200-char preview — "command not
        # found" usually lands past the cut and would otherwise look fixable.
        collector.record_failure(
            CheckFailure(
                command=cmd,
                exit_code=exit_code,
                kind=matched.kind if matched else "project_test",
                failure_class=classify_failure(exit_code, output or preview, ""),
                detail=preview,
            )
        )


def apply_write_edit(
    collector: VerificationCollector,
    args: dict[str, Any],
    result: dict[str, Any],
    add_artifact: Any,
) -> None:
    if not result.get("ok"):
        return
    raw_path = str(result.get("path") or args.get("path") or "")
    path = normalize_workspace_path(raw_path, collector.workspace_root)
    diff = str(result.get("diff") or "")
    content = str(result.get("content") or args.get("content") or "")
    if path:
        collector.paths_touched.add(path)
        if classify_path(path) == "html":
            record_html_check(collector, path, content or diff)
    if diff:
        collector.diffs.append(diff)
        add_artifact("diff", f"edited {raw_path}", path=raw_path, ok=True, detail=diff[:400])


def apply_read(
    collector: VerificationCollector,
    args: dict[str, Any],
    result: dict[str, Any],
    add_artifact: Any,
) -> None:
    if not result.get("ok"):
        return
    path = str(result.get("path") or args.get("path") or "")
    if path:
        collector.paths_read.add(path)
        add_artifact("read", f"read {path}", path=path, ok=True)


def apply_bash(
    collector: VerificationCollector,
    args: dict[str, Any],
    result: dict[str, Any],
    add_artifact: Any,
) -> None:
    cmd = str(args.get("command") or "")
    collector.last_bash_command = cmd
    rc = result.get("returncode")
    if rc is not None:
        collector.last_bash_exit = int(rc)
    ok = bool(result.get("ok"))
    raw = str(result.get("output") or "")
    preview = raw[:200].replace("\n", " ")
    add_artifact("command", cmd[:120], ok=ok, detail=preview)
    record_bash_check(
        collector,
        cmd,
        ok=ok,
        exit_code=int(rc or (0 if ok else 1)),
        preview=preview,
        add_artifact=add_artifact,
        output=raw[:4000],
    )


def unfounded_claim_reason(collector: VerificationCollector, text: str) -> str | None:
    body = (text or "").strip()
    if not body:
        return None
    verified = collector.has_passing_tests()
    # A report that spells out its failures is not making an unfounded claim —
    # do not make it argue with the same blocker twice.
    disclosed = discloses_failures(body)
    if _EVIDENCE_CLAIM_RE.search(body) and not verified and not disclosed:
        return (
            "Submit blocked: summary claims tests/build passed but no passing verification command "
            "was recorded for the touched artifacts. Run the applicable check first."
        )
    if not _DONE_CLAIM_RE.search(body):
        return None
    if not collector.has_edits():
        # Read-only / Q&A / info turns need no evidence to close — only
        # false "tests pass" claims are blocked (checked above).
        return None
    plan = collector.plan()
    if not plan.required_checks:
        # Docs/config/other-only edits have nothing verifiable — submit freely.
        return None
    if plan_status(plan, collector._records) != "verified":
        return (
            "Submit blocked: workspace was edited but required verification is incomplete. "
            "Run the applicable check for the changed files, then submit again."
        )
    return None


def _missing_verification_section(body: str, *, need_verification: bool = True) -> str | None:
    lower = body.lower()
    for header in ("## done", "## changed"):
        if header not in lower:
            return (
                "Submit blocked: include ## Done, ## Changed, and ## Verification sections "
                "(e.g. `## Done`, `## Changed`, `## Verification` with `- ✓ <command>`). "
                "Do not claim done without checkable evidence."
            )
    if not need_verification:
        return None
    # A `## Blocked` section (or a `- ✗ <command>` line) is the honest spelling of
    # "this check did not pass" — it satisfies the section requirement on its own.
    if "## verification" not in lower and not discloses_failures(body):
        return (
            "Submit blocked: include a ## Verification section listing commands you ran "
            "(e.g. `- ✓ pytest -q`). Do not claim done without checkable evidence."
        )
    # A `## Blocked` section already says what did not pass — it stands in for the
    # checked item, so naming the blocker is enough.
    if not re.search(r"[-*]\s*[✓✗]", body) and not _BLOCKED_SECTION_RE.search(body):
        return (
            "Submit blocked: ## Verification must list at least one checked item "
            "(e.g. `- ✓ pytest -q — 42 passed`), or name the blocker under `## Blocked`."
        )
    return None


def next_required_check_command(collector: VerificationCollector) -> str | None:
    """First unsatisfied required check command for submit/idle nudges."""
    plan = collector.plan()
    if not plan.required_checks:
        return None
    for check in plan.required_checks:
        if not check.command:
            continue
        matching = [r for r in collector._records if record_satisfies_check(r, check)]
        if any(r.ok for r in matching):
            continue
        return check.command
    return None


def check_attempts(collector: VerificationCollector, command: str) -> int:
    """How many times this exact command has already been run."""
    norm = normalize_check_command(command)
    if not norm:
        return 0
    return sum(1 for r in collector._records if normalize_check_command(r.command) == norm)


def blocking_failures(collector: VerificationCollector) -> list[CheckFailure]:
    """Failures the agent can actually act on."""
    return [f for f in collector.failures if not f.unfixable]


def unfixable_failures(collector: VerificationCollector) -> list[CheckFailure]:
    """Failures no retry can fix — missing runner, timeout, sandbox, network."""
    return [f for f in collector.failures if f.unfixable]


def _honest_report_accepted(collector: VerificationCollector, attempt: int) -> bool:
    """Whether a report naming its failures may go through on this attempt.

    An unfixable failure is accepted straight away — retrying a command that
    cannot exist only burns budget. A real failure, or a check that was never
    run, is accepted once the retries are spent so the run ends on an honest
    report instead of a budget error.
    """
    fixable = blocking_failures(collector)
    if fixable:
        return attempt >= MAX_BLOCKED_SUBMITS
    if collector.failures:
        return True
    return attempt >= MAX_BLOCKED_SUBMITS


def _escalate_submit_block(reason: str, attempt: int) -> str:
    """Repeat blocks stop suggesting a retry — they name the way through."""
    if attempt < 2:
        return reason
    if attempt < MAX_BLOCKED_SUBMITS:
        return (
            f"{reason}\n\nBlocked {attempt} of {MAX_BLOCKED_SUBMITS} attempts. Re-running the same "
            "check will not clear this. Either fix the cause, or submit honestly with a "
            "`## Blocked` section (or a `- ✗ <command>` line) naming what is still broken."
        )
    return (
        f"{reason}\n\nBlocked {attempt} times — this run has exhausted its submission retries. "
        "Resume with a concrete fix or an honest `## Blocked` report naming what is still broken."
    )


def _evidence_block_reason(
    collector: VerificationCollector,
    plan: VerificationPlan,
    st: VerificationTerminal,
    body: str,
) -> str | None:
    """Stable, attempt-independent reason a submit cannot proceed yet."""
    fixable = blocking_failures(collector)
    if fixable:
        reason = (
            f"Submit blocked: {fixable[0].text}. "
            "Fix the failure and re-run verification before submitting."
        )
        cmd = next_required_check_command(collector)
        if cmd:
            reason += f"\n\nSuggested command: `{cmd}`"
        return reason

    unfixable = unfixable_failures(collector)
    if unfixable:
        lines = "\n".join(f"- {f.text}" for f in unfixable[:3])
        return (
            "Submit blocked: verification could not complete.\n"
            f"{lines}\n\nNo retry can fix this. Say so in the report — add a `## Blocked` section "
            "(or a `- ✗ <command>` line under `## Verification`) naming what you could not verify."
        )

    if collector.gaps and st == "failed":
        return f"Submit blocked: {collector.gaps[0]}. Fix the failure and re-run verification before submitting."

    if collector.has_edits() and plan.required_checks and st != "verified":
        kinds = ", ".join(sorted(plan.artifact_kinds))
        reason = (
            f"Submit blocked: workspace was edited ({kinds}) but required verification is incomplete. "
            "Run the applicable check for the changed files, then submit again."
        )
        cmd = next_required_check_command(collector)
        if cmd:
            reason += f"\n\nSuggested command: `{cmd}`"
        return reason

    return unfounded_claim_reason(collector, body)


def submit_block_reason(
    collector: VerificationCollector,
    submission: str = "",
    *,
    require_verification: bool = True,
    require_verification_section: bool = True,
    structured: bool = True,
) -> str | None:
    """Why a submit is blocked, or None when it may proceed.

    ``structured`` is True for the ``submit`` tool (Done/Changed/Verification
    sections required for verifiable code edits) and False for the legacy
    bash marker / prose path, which carries a free-form summary — there only
    the evidence itself is gated (checks complete, no false claims), never
    the section format.

    Blocking is finite by design. Early blocks explain the failure and the
    command to run; later ones escalate to the sanctioned honest report
    (``## Blocked`` or a ``- ✗ <command>`` line). Once that report is on the
    table the submit goes through — a check the agent cannot fix must not eat
    the rest of the step and token budget.
    """
    if not require_verification:
        collector.clear_submit_blocks()
        return None

    plan = collector.plan()
    st = plan_status(plan, collector._records)
    body = (submission or "").strip()
    attempt = collector.blocked_submits + 1
    accepted = discloses_failures(body) and _honest_report_accepted(collector, attempt)

    if not accepted:
        reason = _evidence_block_reason(collector, plan, st, body)
        if reason is not None:
            streak = collector.note_submit_block(reason)
            return _escalate_submit_block(reason, streak)

    if (
        require_verification_section
        and structured
        and collector.has_edits()
        and body
        and bool(plan.required_checks)
    ):
        section = _missing_verification_section(body, need_verification=True)
        if section is not None:
            streak = collector.note_submit_block(section)
            return _escalate_submit_block(section, streak)

    # An honest report is not a fix — keep the streak so the next attempt still
    # knows the check never went green. Reset only once the evidence is clean.
    if not collector.failures and st == "verified":
        collector.clear_submit_blocks()
    return None


def post_edit_nudge(collector: VerificationCollector) -> str | None:
    plan = collector.plan()
    if not collector.has_edits() or not plan.required_checks:
        return None
    if plan_status(plan, collector._records) == "verified":
        return None
    kinds = ", ".join(sorted(plan.artifact_kinds))
    if plan.package_count > 1:
        return (
            f"[verification] Edits span {plan.package_count} workspace packages ({kinds}) — "
            "run the applicable check in each affected package before submitting."
        )
    if kinds == "html":
        return "[verification] HTML edited — structural parse will be checked; pytest is not required."
    return (
        f"[verification] Edits recorded ({kinds}) — run the applicable check for the changed files "
        "before submitting."
    )
