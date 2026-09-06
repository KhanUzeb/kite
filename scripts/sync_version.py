#!/usr/bin/env python3
# kite-release-version: 0.9.1
"""Keep Kite version stamps in sync with pyproject.toml.

Usage:
  python scripts/sync_version.py              # sync all files to pyproject version
  python scripts/sync_version.py 0.9.1        # set pyproject + all stamps to 0.9.1
  python scripts/sync_version.py --check      # exit 1 if any stamp differs

Called by scripts/bump_release.sh and CI on every push/tag.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SCRIPTS_DIR = ROOT / "scripts"
SCRIPT_MARKER = re.compile(r"(?m)^# kite-release-version: [\d.]+$")
SCRIPT_SUFFIXES = {".sh", ".ps1", ".py"}


@dataclass(frozen=True)
class StampRule:
    path: Path
    pattern: str
    repl: str  # use {v} for version


RULES: tuple[StampRule, ...] = (
    StampRule(PYPROJECT, r'(?m)^version = "[^"]+"', 'version = "{v}"'),
    StampRule(ROOT / "src/kite/__init__.py", r'__version__ = "[^"]+"', '__version__ = "{v}"'),
    StampRule(
        ROOT / "README.md",
        r"version-[\d.]+-cyan",
        "version-{v}-cyan",
    ),
    StampRule(ROOT / "README.md", r"\*\*Version:\*\* [\d.]+", "**Version:** {v}"),
    StampRule(ROOT / "AGENTS.md", r"\*\*Kite\*\* v[\d.]+", "**Kite** v{v}"),
    StampRule(ROOT / "architecture.md", r"\*\*Version:\*\* [\d.]+", "**Version:** {v}"),
    StampRule(ROOT / "docs/cli-ux.md", r"\*\*Version:\*\* [\d.]+", "**Version:** {v}"),
    StampRule(ROOT / "docs/kite-system-design.md", r"\*\*Version:\*\* [\d.]+", "**Version:** {v}"),
    StampRule(
        ROOT / "docs/ideal-cli-spec.md",
        r"# Ideal CLI spec coverage \(Kite [\d.]+\)",
        "# Ideal CLI spec coverage (Kite {v})",
    ),
    StampRule(
        ROOT / "scripts/bump_release.sh",
        r"(?m)^#   ./scripts/bump_release\.sh [\d.]+$",
        "#   ./scripts/bump_release.sh {v}",
    ),
    StampRule(
        SCRIPTS_DIR / "sync_version.py",
        r"  python scripts/sync_version\.py [\d.]+\s+# set pyproject \+ all stamps to [\d.]+",
        "  python scripts/sync_version.py {v}        # set pyproject + all stamps to {v}",
    ),
)


def read_pyproject_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit("pyproject.toml missing project.version")
    return version.strip()


def write_pyproject_version(version: str) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text, n = re.subn(r'(?m)^version = "[^"]+"', f'version = "{version}"', text, count=1)
    if n != 1:
        raise SystemExit("could not update pyproject.toml version")
    PYPROJECT.write_text(new_text, encoding="utf-8")


def apply_rule(path: Path, rule: StampRule, version: str) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    replacement = rule.repl.format(v=version)
    new_text, n = re.subn(rule.pattern, replacement, text, count=1)
    if n == 0:
        return False
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return True


def sync_script_markers(version: str) -> list[str]:
    """Stamp # kite-release-version in every scripts/*.{sh,ps1,py}."""
    updated: list[str] = []
    if not SCRIPTS_DIR.is_dir():
        return updated
    marker_line = f"# kite-release-version: {version}\n"
    for path in sorted(SCRIPTS_DIR.iterdir()):
        if not path.is_file() or path.suffix not in SCRIPT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        if SCRIPT_MARKER.search(text):
            new_text = SCRIPT_MARKER.sub(f"# kite-release-version: {version}", text, count=1)
        else:
            lines = text.splitlines(keepends=True)
            if lines and lines[0].startswith("#!"):
                new_text = lines[0] + marker_line + "".join(lines[1:])
            else:
                new_text = marker_line + text
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            updated.append(path.relative_to(ROOT).as_posix())
    return updated


def check_script_markers(expected: str) -> list[str]:
    errors: list[str] = []
    if not SCRIPTS_DIR.is_dir():
        return errors
    for path in sorted(SCRIPTS_DIR.iterdir()):
        if not path.is_file() or path.suffix not in SCRIPT_SUFFIXES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        match = SCRIPT_MARKER.search(text)
        if not match:
            errors.append(f"{rel}: missing # kite-release-version marker")
            continue
        found = match.group(0).split(":", 1)[-1].strip()
        if found != expected:
            errors.append(f"{rel}: marker is {found!r}, expected {expected!r}")
    return errors


def sync_version(version: str) -> list[str]:
    write_pyproject_version(version)
    updated: list[str] = []
    seen: set[Path] = set()
    for rule in RULES:
        if apply_rule(rule.path, rule, version):
            rel = rule.path.relative_to(ROOT).as_posix()
            if rel not in updated:
                updated.append(rel)
        seen.add(rule.path)
    for rel in sync_script_markers(version):
        if rel not in updated:
            updated.append(rel)
    return updated


def check_version(expected: str) -> list[str]:
    errors: list[str] = []
    if read_pyproject_version() != expected:
        errors.append(
            f"pyproject.toml has {read_pyproject_version()}, expected {expected}",
        )

    try:
        sys.path.insert(0, str(ROOT / "src"))
        from kite import __version__ as pkg_version  # noqa: PLC0415

        if pkg_version != expected:
            errors.append(f"kite.__version__ is {pkg_version}, expected {expected}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"could not import kite.__version__: {exc}")
    finally:
        if str(ROOT / "src") in sys.path:
            sys.path.remove(str(ROOT / "src"))

    for rule in RULES:
        rel = rule.path.relative_to(ROOT).as_posix()
        if not rule.path.is_file():
            errors.append(f"missing {rel}")
            continue
        text = rule.path.read_text(encoding="utf-8")
        replacement = rule.repl.format(v=expected)
        new_text, n = re.subn(rule.pattern, replacement, text, count=1)
        if n == 0:
            errors.append(f"{rel}: pattern not found ({rule.pattern!r})")
        elif new_text != text:
            errors.append(f"{rel}: stamp is not {expected!r}")

    errors.extend(check_script_markers(expected))

    release_doc = ROOT / f"docs/RELEASE-{expected}.md"
    if not release_doc.is_file():
        errors.append(f"missing {release_doc.relative_to(ROOT)}")
    changelog = ROOT / "CHANGELOG.md"
    if f"[{expected}]" not in changelog.read_text(encoding="utf-8"):
        errors.append(f"CHANGELOG.md missing section for {expected}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="target version (default: read pyproject.toml)")
    parser.add_argument("--check", action="store_true", help="verify stamps match pyproject version")
    args = parser.parse_args(argv)

    if args.check:
        expected = args.version or read_pyproject_version()
        errors = check_version(expected)
        if errors:
            for err in errors:
                print(f"sync_version: {err}", file=sys.stderr)
            return 1
        print(f"sync_version: ok ({expected})")
        return 0

    version = args.version or read_pyproject_version()
    updated = sync_version(version)
    for path in updated:
        print(f"updated {path} -> {version}")
    if not updated:
        print(f"version stamps already at {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
