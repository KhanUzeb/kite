"""Verification plan — artifact-aware, workspace-scoped check selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from kite.application.verification.workspace_profile import (
    WorkspaceProfile,
    _python_command_for_paths,
    group_paths_by_package,
)

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
    paths = tuple(p for p in touched_paths if p)
    kinds = classify_touched_paths(paths)
    required: list[CheckSpec] = []
    optional: list[CheckSpec] = []

    if "python" in kinds:
        required.extend(_python_checks(paths, profile))
    if "html" in kinds:
        required.extend(_html_checks(paths))
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
