"""Tests for SoL-Pi harness mechanisms (arXiv:2609.20519)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from kite.agent.hooks import HookBus
from kite.sol_pi.action_fusion import THEN_RUN_SUCCEEDED, merge_then_run_output, run_mutation_then_run
from kite.sol_pi.config import load_sol_pi_config
from kite.sol_pi.economics import decide_compaction, estimate_remaining_requests
from kite.sol_pi.evidence import (
    REDUCER_RECEIPT_SCHEMA,
    ArchiveObject,
    is_diagnostic_command,
    receipt_text,
    sha256_text,
    validate_receipt,
)
from kite.sol_pi.integration import attach_sol_pi
from kite.sol_pi.observation_core import (
    FULL_SENDS,
    THRESHOLD_BYTES,
    create_observation,
    ensure_stored,
    placeholder_for,
    read_recall_chunk,
)
from kite.sol_pi.plan import analyze_plan_transition, parse_todo_items


@dataclass
class _HarnessStub:
    hooks: HookBus = field(default_factory=HookBus)
    sol_pi: object | None = field(default=None, init=False)


def test_sol_pi_config_load_and_attach(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    missing = load_sol_pi_config(tmp_path)
    assert missing.action_fusion is False
    assert missing.observation_pack is False
    assert missing.evidence_preserving_reducer is False
    assert missing.online_context_compact is False
    assert missing.enabled is False

    harness = _HarnessStub()
    assert attach_sol_pi(harness, str(tmp_path)) is None
    assert harness.sol_pi is None
    assert "sol_pi_session" not in harness.hooks.context

    kite_dir = tmp_path / ".kite"
    kite_dir.mkdir()
    (kite_dir / "sol-pi.json").write_text(
        json.dumps({"version": 1, "actionFusion": True, "observationPack": True}),
        encoding="utf-8",
    )
    # Anchor project-root discovery at tmp_path so ancestor markers
    # (e.g. a dotfiles git repo at $HOME) cannot shadow the fixture.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='sol-pi-fixture'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = load_sol_pi_config(tmp_path)
    assert cfg.action_fusion is True
    assert cfg.observation_pack is True
    assert cfg.enabled is True


def test_economics_horizon_and_gate() -> None:
    horizon = estimate_remaining_requests(
        completed_boundary_request_counts=(4, 6, 5),
        remaining_boundaries=3,
        scale=1.0,
        standard_deviation_k=0.0,
        context_tokens=100_000,
        context_window_tokens=200_000,
        average_context_token_increment=5_000.0,
    )
    assert horizon.requests_per_boundary_mean == 5.0
    assert horizon.expected_remaining_requests == 16

    assert decide_compaction(
        write_tokens=80_000,
        archive_tokens=60_000,
        memo_tokens=1_000,
        context_tokens=80_000,
        completed_boundary_request_counts=(4, 6, 5),
        remaining_boundaries=4,
        average_context_token_increment=2_000.0,
        context_window_tokens=200_000,
        prior_compaction_count=0,
        carried_debt_tokens=0,
        cache_debt_repayment_tokens=0,
        cache_write_read_ratio=1.0,
    ).compact is True

    assert (
        decide_compaction(
            write_tokens=80_000,
            archive_tokens=500,
            memo_tokens=1_000,
            context_tokens=80_000,
            completed_boundary_request_counts=(4, 6, 5),
            remaining_boundaries=4,
            average_context_token_increment=2_000.0,
            context_window_tokens=200_000,
            prior_compaction_count=0,
            carried_debt_tokens=0,
            cache_debt_repayment_tokens=0,
            cache_write_read_ratio=1.0,
        ).reason
        == "non_positive_saving"
    )


def test_observation_pack_threshold_and_recall(tmp_path: Path) -> None:
    text = "line\n" * (THRESHOLD_BYTES // 5 + 10)
    obs = create_observation("bash", "call-1", text, tmp_path)
    assert obs is not None
    ensure_stored(obs)
    assert obs.file_path.is_file()
    placeholder = placeholder_for(obs)
    assert obs.id in placeholder
    chunk = read_recall_chunk(obs.file_path, 0, max_bytes=4096, max_lines=50)
    assert chunk.bytes > 0
    assert FULL_SENDS == 2


def test_evidence_receipt_and_plan_transition() -> None:
    body = "FAILED test_foo\n" + ("x" * 5000)
    digest = sha256_text(body)
    archive = ArchiveObject(hash=digest, bytes=len(body), lines=2, body=body)
    assert is_diagnostic_command("pytest -q")
    raw = json.dumps(
        {
            "schema": REDUCER_RECEIPT_SCHEMA,
            "source_sha256": digest,
            "status": "failure",
            "uncertain": False,
            "evidence": [{"kind": "failure", "quote": "FAILED test_foo"}],
        }
    )
    validated, reason = validate_receipt(raw, archive, body, True)
    assert reason == "ok"
    assert validated is not None
    rendered = receipt_text(validated, archive, "pytest -q")
    assert "sol_pi_evidence_receipt_v1" in rendered

    prev = parse_todo_items([{"content": "a", "status": "in_progress"}])
    assert prev is not None
    nxt = parse_todo_items(
        [
            {"content": "a", "status": "completed"},
            {"content": "b", "status": "pending"},
        ]
    )
    assert nxt is not None
    transition = analyze_plan_transition(prev, nxt)
    assert len(transition.completed_steps) == 1


def test_action_fusion_then_run_and_merge(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old\n", encoding="utf-8")

    def mutate() -> dict:
        target.write_text("new\n", encoding="utf-8")
        return {"ok": True, "output": "edited"}

    def bash(_args: dict) -> dict:
        return {"ok": True, "output": "ok", "returncode": 0}

    out = run_mutation_then_run(target, {"command": "true"}, mutate, bash)
    assert THEN_RUN_SUCCEEDED in str(out.get("output"))

    merged = merge_then_run_output(
        {"ok": True, "output": "wrote"},
        {"ok": False, "output": "fail", "returncode": 1},
    )
    assert THEN_RUN_SUCCEEDED in merged["output"]
    assert merged.get("then_run_exit") == 1
