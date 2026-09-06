"""Workspace verification profile — monorepo-aware check discovery."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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


def _posix_rel(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()


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


def _default_rust_test(directory: Path) -> str:
    return "cargo test"


def _default_go_test(directory: Path, rel_root: str) -> str:
    if rel_root:
        return f"go test ./{rel_root}/..."
    return "go test ./..."


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
            rel = _posix_rel(workspace, directory) if directory != workspace else ""
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
                    test_cmd = _default_rust_test(directory)
                elif "go" in ecosystems:
                    test_cmd = _default_go_test(directory, rel)
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
