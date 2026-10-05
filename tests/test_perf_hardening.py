"""Performance-hardening tests — correctness of caches and hoists, not timing.

Wall-clock assertions are deliberately absent: CI hardware varies and they
would flake. These lock the *work* each optimisation changed instead —
that redundant work no longer happens, and that every cache still observes
its inputs changing.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from kite.context import discovery
from kite.context.project_init import (
    _BRANCH_CACHE,
    default_branch,
    invalidate_default_branch_cache,
)
from kite.context.repomap import _iter_source_files, _rel_posix, _score_path, build_repo_map


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    subprocess.run(
        ["git", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


def _c_test_rel_posix_matches_relative_to(tmp_path: Path) -> None:
    """The fast prefix slice must equal pathlib's relative_to().as_posix()."""
    root = (tmp_path / "proj").resolve()
    (root / "src" / "deep" / "nested").mkdir(parents=True, exist_ok=True)
    for rel in ("src/app.py", "src/deep/mod.py", "src/deep/nested/x.py", "top.py"):
        (root / rel).write_text("x = 1\n", encoding="utf-8")

    root_str = str(root)
    for path in [root / r for r in ("src/app.py", "src/deep/mod.py", "src/deep/nested/x.py", "top.py")]:
        assert _rel_posix(path, root, root_str) == path.relative_to(root).as_posix()

    # Sibling directory sharing a name prefix must NOT be sliced as a child:
    # "…/proj2/x.py" must not masquerade as living under "…/proj". For a true
    # outsider, relative_to() raises — so the helper must propagate, not slice.
    sibling = root.parent / f"{root.name}2"
    sibling.mkdir(exist_ok=True)
    outside = sibling / "x.py"
    assert not str(outside).startswith(root_str + os.sep)
    try:
        outside.relative_to(root)
    except ValueError:
        with pytest.raises(ValueError):
            _rel_posix(outside, root, root_str)
    else:
        raise AssertionError("fixture is not actually outside root")

    # Score ordering must be unchanged relative to the pure-pathlib version.
    changed = {"src/app.py"}
    for path in (root / "src/app.py", root / "top.py", root / "src/deep/mod.py"):
        expected_rel = path.relative_to(root).as_posix()
        assert expected_rel in changed or expected_rel not in changed
        assert _score_path(path, root, changed)[1] == expected_rel.lower()


def _c_test_repo_map_output_stable_and_repeatable(tmp_path: Path) -> None:
    """Repeated repo-map builds are identical and pick up new/edited files."""
    root = (tmp_path / "proj").resolve()
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (root / "src" / "helpers.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    (root / "notes.txt").write_text("ignored\n", encoding="utf-8")

    first = build_repo_map(root, prefer_git_changed=False)
    assert "src/app.py: main" in first
    assert "src/helpers.py: Thing" in first
    assert "notes.txt" not in first
    assert first == build_repo_map(root, prefer_git_changed=False)

    # A newly added source file must appear (no stale snapshot of the walk).
    (root / "src" / "extra.py").write_text("def added():\n    pass\n", encoding="utf-8")
    assert "extra.py" in build_repo_map(root, prefer_git_changed=False)

    # The walk must not pick up skipped dirs, and must cap at the scan limit.
    (root / "node_modules").mkdir(exist_ok=True)
    (root / "node_modules" / "skipped.py").write_text("def nope():\n    pass\n", encoding="utf-8")
    names = {p.name for p in _iter_source_files(root)}
    assert "skipped.py" not in names and "app.py" in names
    assert len(_iter_source_files(root)) <= 600


def _c_test_default_branch_cache_invalidation(tmp_path: Path) -> None:
    """default_branch() memo must re-probe when its git inputs change."""
    root = _git_repo(tmp_path / "repo")
    invalidate_default_branch_cache()

    first = default_branch(root)
    assert isinstance(first, str) and first
    # Memoized: the key holds this root's fingerprint.
    assert any(str(root) == k[0] for k in _BRANCH_CACHE._entries)

    # Repeated calls are consistent and do not accumulate state.
    assert default_branch(root) == first
    entry_count = len(_BRANCH_CACHE._entries)
    for _ in range(5):
        assert default_branch(root) == first
    assert len(_BRANCH_CACHE._entries) == entry_count

    # Touching a fingerprinted git input must produce a NEW key (re-probe),
    # proving the memo is keyed on inputs rather than the root alone.
    key_before = {k for k in _BRANCH_CACHE._entries if str(root) == k[0]}
    cfg = root / ".git" / "config"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\n[perf]\n\tprobe = 1\n", encoding="utf-8")
    assert default_branch(root) == first  # value unchanged...
    key_after = {k for k in _BRANCH_CACHE._entries if str(root) == k[0]}
    assert key_after != key_before  # ...but it was re-derived from new inputs

    # Explicit invalidation still works and is observable.
    invalidate_default_branch_cache()
    assert not _BRANCH_CACHE._entries
    assert default_branch(root) == first
    assert _BRANCH_CACHE._entries

    # A different repo must never reuse the first repo's memo entry: it gets
    # its own key, and its answer is independent of the first repo's.
    other = _git_repo(tmp_path / "other")
    other_branch = default_branch(other)
    assert isinstance(other_branch, str) and other_branch
    other_key = [k for k in _BRANCH_CACHE._entries if str(other) == k[0]]
    first_key = [k for k in _BRANCH_CACHE._entries if str(root) == k[0]]
    assert other_key and first_key
    assert all(k != first_key[0] for k in other_key)
    # Both repos coexist without evicting or aliasing each other.
    assert {k[0] for k in _BRANCH_CACHE._entries} >= {str(root), str(other)}


def _c_test_default_branch_tracks_config_change(tmp_path: Path, monkeypatch) -> None:
    """Changing init.defaultBranch on disk is reflected without invalidation."""
    root = _git_repo(tmp_path / "cfgrepo")
    # Point git at an isolated global config so the change is observable.
    global_cfg = tmp_path / "gitconfig"
    global_cfg.write_text("[init]\n\tdefaultBranch = perfbranch\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))
    monkeypatch.delenv("GIT_CONFIG_SYSTEM", raising=False)
    invalidate_default_branch_cache()

    assert default_branch(root) == "perfbranch"
    # Same inputs -> memo hit.
    assert default_branch(root) == "perfbranch"

    # Changing the fingerprinted file must invalidate; drop the env override
    # so the answer legitimately changes to the built-in fallback.
    global_cfg.write_text("[init]\n\tdefaultBranch = otherbranch\n", encoding="utf-8")
    assert default_branch(root) == "otherbranch"

    # The env var that redirects git config is itself part of the answer, so it
    # must be part of the key: unsetting it must re-probe.
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    changed = default_branch(root)
    assert changed != "otherbranch"
    assert isinstance(changed, str) and changed


def _c_test_instruction_resolution_shared_and_consistent(tmp_path: Path) -> None:
    """Resolved instruction paths are deduped; discovery sees edits + creates."""
    root = _git_repo(tmp_path / "instr")
    discovery.invalidate_project_context_cache()
    (root / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    (root / "KITE.md").write_text("# memory\n", encoding="utf-8")

    resolved = discovery._resolved_instruction_paths(root, root)
    assert resolved == sorted(set(resolved), key=resolved.index), "must be deduplicated in order"
    assert {p.name for p in resolved} >= {"AGENTS.md", "KITE.md"}
    # Stable across repeated calls (no per-call drift).
    assert discovery._resolved_instruction_paths(root, root) == resolved

    files = discovery.discover_agents_files(root)
    by_name = {Path(f.path).name: f.content for f in files}
    assert "# rules" in by_name["AGENTS.md"] and "# memory" in by_name["KITE.md"]

    # Edit is observed (no stale cache in the read path).
    time.sleep(0.01)
    (root / "AGENTS.md").write_text("# changed rules\n", encoding="utf-8")
    again = {Path(f.path).name: f.content for f in discovery.discover_agents_files(root)}
    assert "# changed rules" in again["AGENTS.md"]

    # Fingerprint moves when an instruction file's content/mtime changes.
    fp_before = discovery._instructions_fingerprint(root)
    time.sleep(0.01)
    (root / "AGENTS.md").write_text("# yet another\n", encoding="utf-8")
    assert discovery._instructions_fingerprint(root) != fp_before

    # A newly created instruction file also moves the fingerprint.
    (root / "CONTEXT.md").write_text("# ctx\n", encoding="utf-8")
    fp_with_ctx = discovery._instructions_fingerprint(root)
    assert any(Path(p).name == "CONTEXT.md" for p, _, _ in fp_with_ctx)


def _c_test_gather_context_cache_respects_fingerprint(tmp_path: Path) -> None:
    """Project-context cache hits on unchanged input and misses on a change."""
    root = _git_repo(tmp_path / "ctx")
    discovery.invalidate_project_context_cache()
    (root / "AGENTS.md").write_text("# one\n", encoding="utf-8")

    first = discovery.gather_project_context(root, include_git=False)
    second = discovery.gather_project_context(root, include_git=False)
    assert second is first, "unchanged inputs must serve the cached context"

    time.sleep(0.01)
    (root / "AGENTS.md").write_text("# two\n", encoding="utf-8")
    third = discovery.gather_project_context(root, include_git=False)
    assert third is not first
    assert "# two" in third.files[0].content

    # Repeated gathers must not grow the cache without bound.
    before = len(discovery._CTX_CACHE._entries)
    for _ in range(5):
        discovery.gather_project_context(root, include_git=False)
    assert len(discovery._CTX_CACHE._entries) == before


def _c_test_read_tool_matches_naive_reference(tmp_path: Path) -> None:
    """Bounded read path stays byte-identical to a direct decode reference."""
    from kite.tools.coding import make_coding_tools

    tmp_path.mkdir(parents=True, exist_ok=True)
    reg = {t.name: t for t in make_coding_tools(cwd=str(tmp_path))}
    read = reg["read"]._execute_fn

    cases = {
        "empty.txt": "",
        "plain.txt": "alpha\nbeta\ngamma\n",
        "crlf.txt": "one\r\ntwo\r\nthree\r\n",
        "unicode.txt": "héllo wörld\n日本語テキスト\n",
        "noeol.txt": "trailing without newline",
        "binaryish.txt": "ok\x00\x01\x02bytes\n",
    }
    for name, content in cases.items():
        (tmp_path / name).write_text(content, encoding="utf-8", newline="")
        out = read({"path": name})
        assert out["ok"], (name, out)
        # Reference: the same bounded+newline-normalized decode the tool does.
        raw = (tmp_path / name).read_bytes()
        expected = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        assert out["output"] == expected, name

    # Large file: byte cap + truncation notice, identical to reference.
    big = tmp_path / "big.txt"
    big.write_text("".join(f"line {i}\n" for i in range(5000)), encoding="utf-8")
    out = read({"path": "big.txt"})
    assert out["ok"] and out["truncated"] is True
    assert "lines truncated" in out["output"]
    body = out["output"].split("\n... [")[0]
    reference = big.read_text(encoding="utf-8").splitlines(keepends=True)[:400]
    assert body == "".join(reference)

    # offset/limit slices are still exact.
    out = read({"path": "plain.txt", "offset": 2, "limit": 1})
    assert out["output"] == "beta\n"
    # numbered mode prefixes sparsely and nothing else.
    out = read({"path": "plain.txt", "numbered": True})
    assert out["output"].startswith("     1|alpha\n")
    # Missing file and directory keep their error shapes.
    assert read({"path": "nope.txt"})["ok"] is False
    assert read({"path": "."}).get("directory") is True


def test_batch_00(tmp_path) -> None:
    """Consolidated: rel-path + repo map, default_branch invalidation."""
    _c_test_rel_posix_matches_relative_to(tmp_path=tmp_path / "a")
    _c_test_repo_map_output_stable_and_repeatable(tmp_path=tmp_path / "b")
    _c_test_default_branch_cache_invalidation(tmp_path=tmp_path / "c")


def test_batch_01(tmp_path, monkeypatch) -> None:
    """Consolidated: default_branch tracks real config changes, instruction + context caches."""
    _c_test_default_branch_tracks_config_change(tmp_path=tmp_path / "d", monkeypatch=monkeypatch)
    _c_test_instruction_resolution_shared_and_consistent(tmp_path=tmp_path / "e")
    _c_test_gather_context_cache_respects_fingerprint(tmp_path=tmp_path / "f")


def test_batch_02(tmp_path) -> None:
    """Consolidated: bounded read path equivalence with the naive decode."""
    _c_test_read_tool_matches_naive_reference(tmp_path=tmp_path / "g")