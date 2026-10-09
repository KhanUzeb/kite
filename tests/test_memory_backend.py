"""Memory backend hardening — traversal, corruption, concurrency, analytics edges.

Every test here corresponds to a defect that reproduced as a crash, a silent
data loss, or a duplicated note. Tests use the shared ``kite_home`` fixture so
no path ever resolves into the real ~/.kite.

"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from kite.memory import session as session_mod
from kite.memory import session_format
from kite.memory.audit import AuditLog
from kite.memory.context_checkpoint import (
    checkpoints_dir,
    list_checkpoints,
    load_checkpoint,
    save_checkpoint,
)
from kite.memory.episodic import EpisodicStore
from kite.memory.goal import SessionGoal, save_session_goal
from kite.memory.handoff import write_handoff
from kite.memory.secure_io import storage_id
from kite.memory.semantic import SemanticStore
from kite.memory.session import Session, create_session
from kite.memory.session_analytics import scan_session_file
from kite.memory.store import MemoryStore, _migrate_jsonl
from kite.memory.working_style import observe_session_turn

# Ids a CLI, tool call, or model can hand to a filename builder.
_FUZZ_IDS: tuple[tuple[str, str], ...] = (
    ("../../etc/passwd", "posix traversal"),
    ("..\\..\\windows\\system32", "windows traversal"),
    ("C:\\evil", "drive-absolute"),
    ("", "empty"),
    (".", "dot"),
    ("..", "dotdot"),
    ("a/b", "forward slash"),
    ("a\\b", "backslash"),
    ("a\x00b", "nul byte"),
    ("   ", "whitespace only"),
    ("... ", "dot run"),
    ("x" * 10_000, "pathologically long"),
)


def _session(tmp_path: Path, task: str = "demo") -> Session:
    s = create_session(task=task, cwd=str(tmp_path), provider="p", model="m")
    s.append({"role": "user", "content": task})
    return s


# --- 1. path traversal / id safety -------------------------------------------


def test_fuzzed_ids_never_escape_their_storage_root(kite_home: Path) -> None:
    """No id from user/tool/model input may resolve outside its storage root.

    Every builder that turns a session id into a filename funnels through
    ``storage_id``, so that is the single choke point to fuzz. Traversal was
    already refused; a pathologically long id was *not* — it passed validation
    and only failed later at the OS layer with a bare ``OSError: [Errno 22]``,
    which surfaced as an unattributable crash in whatever CLI or tool asked for
    that session instead of a clean rejection at the validation boundary.
    """
    from kite.memory.goal import _goal_path

    roots = {
        "trajectories": (kite_home / "trajectories").resolve(),
        "goals": (kite_home / "goals").resolve(),
        "checkpoints": (kite_home / "checkpoints").resolve(),
    }
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)

    builders = (
        ("storage_id", lambda i: storage_id(i, label="id")),
        ("_trajectory_path", session_mod._trajectory_path),
        ("_goal_path", _goal_path),
        ("checkpoints_dir", checkpoints_dir),
    )

    for bad, label in _FUZZ_IDS:
        for name, fn in builders:
            try:
                out = Path(fn(bad))
            except ValueError:
                continue  # correct rejection at the boundary
            except Exception as exc:  # noqa: BLE001 - this is the defect being pinned
                raise AssertionError(
                    f"{name} raised {type(exc).__name__} instead of ValueError for {label!r}"
                ) from None
            for root in roots.values():
                assert out.resolve().is_relative_to(root), f"{name} escaped for {label!r}: {out}"

    # Separately: resolve_session_path is the CLI/tool entry point and must refuse
    # every one of them too (it wraps ValueError into its own message).
    from kite.memory.session import resolve_session_path

    for bad, _label in _FUZZ_IDS:
        with pytest.raises((ValueError, FileNotFoundError)):
            resolve_session_path(bad)


def test_overlong_session_id_is_rejected_before_touching_the_filesystem(kite_home: Path) -> None:
    """A pathological id must fail as ValueError, not as a raw OSError mid-write."""
    for bad in ("x" * 10_000, "y" * 400):
        with pytest.raises(ValueError):
            save_session_goal(bad, SessionGoal(objective="o"))


def test_reaper_derives_keep_names_from_live_stems(kite_home: Path) -> None:
    """An id that itself ends in ``.meta``/``.stats`` must not orphan its sidecars.

    ``_reap_orphan_sidecars`` builds the keep-set from live ``*.jsonl`` stems
    instead of stripping suffixes off files on disk. That reasoning is sound and
    this locks it in: with id ``tricky.meta`` the transcript is ``tricky.meta.jsonl``
    and its sidecar is ``tricky.meta.meta`` — a suffix-stripping reaper would
    have deleted a live sidecar. A genuinely orphaned sidecar still goes.
    """
    folder = session_mod.sessions_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for stem in ("plain", "tricky.meta", "tricky.stats"):
        (folder / f"{stem}.jsonl").write_text("{}", encoding="utf-8")
        (folder / f"{stem}.meta").write_text("{}", encoding="utf-8")
    (folder / "truly-orphan.meta").write_text("{}", encoding="utf-8")  # no transcript

    session_mod._reap_orphan_sidecars(folder)

    survivors = sorted(p.name for p in folder.iterdir())
    assert survivors == [
        "plain.jsonl",
        "plain.meta",
        "tricky.meta.jsonl",
        "tricky.meta.meta",
        "tricky.stats.jsonl",
        "tricky.stats.meta",
    ], survivors


# --- 2. corruption / crash recovery ------------------------------------------


def test_corrupt_meta_row_does_not_make_a_session_unlistable(kite_home: Path, tmp_path: Path) -> None:
    """A torn *first* line must not silently orphan the whole transcript.

    The post-crash normal case is a half-written final line, which readers skip.
    The inverse — a corrupt meta row — was worse: ``list_sessions`` returned
    nothing, so the session vanished from every picker while the transcript sat
    on disk holding real work, and ``prune_sessions`` could no longer reap it.
    """
    s = _session(tmp_path, "valuable work")
    s.append({"role": "user", "content": "second message"})
    path = s._session_path()

    lines = path.read_text(encoding="utf-8").split("\n")
    for header in ('{"type":"meta"', "[]", '{}', '{"type":"meta","id":"x","created_at":"bad"}'):
        lines[0] = header
        path.write_text("\n".join(lines), encoding="utf-8")
        listed = {m.id: m for m in session_mod.list_sessions(limit=50)}
        assert s.id in listed, "session with a torn meta row became invisible and unlistable"
        assert listed[s.id].label == "Recovered session"
        assert listed[s.id].provider == "p"
        assert session_mod.load_session(s.id).messages == s.messages
        assert session_mod.load_session_tail(s.id, 1).messages == s.messages[-1:]

    path.write_bytes(b"\xff\xfe\n" + "\n".join(lines[1:]).encode("utf-8"))
    assert session_mod._read_session_meta(path).id == s.id
    newer = _session(tmp_path, "newer work")
    os.utime(path, (1, 1))
    os.utime(path.with_suffix(".meta"), (1, 1))
    removed = session_mod.prune_sessions(keep=1, dry_run=False)
    assert [row.id for row in removed] == [s.id]
    assert not path.exists()
    assert newer._session_path().exists()


def test_torn_checkpoint_reports_a_clear_error_instead_of_raw_json(kite_home: Path, tmp_path: Path) -> None:
    """A half-written checkpoint is the normal crash state — it must not raise JSONDecodeError."""
    cp = save_checkpoint(
        session_id="s-torn", messages=[{"role": "user", "content": "x" * 400}], cwd=str(tmp_path)
    )
    path = checkpoints_dir("s-torn") / f"{cp.id}.json"
    blob = path.read_text(encoding="utf-8")
    path.write_text(blob[: len(blob) // 2], encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt|unreadable"):
        load_checkpoint("s-torn", cp.id)
    # The listing path already tolerated it and still does.
    assert list_checkpoints("s-torn") == []


def test_non_finite_sidecar_timestamp_cannot_crash_the_session_picker(kite_home: Path, tmp_path: Path) -> None:
    """A NaN/inf timestamp in the sidecar must not blow up the picker rendering.

    ``json.loads`` happily parses ``NaN`` and ``Infinity`` (both valid JS), so a
    truncated or hand-edited sidecar can hand a non-finite ``updated_at`` to
    ``datetime.fromtimestamp`` — a hard crash in the REPL picker, which renders
    every listed session.
    """
    for bad in (float("nan"), float("inf"), -float("inf")):
        assert session_format.format_session_when(bad, now=0.0) == (
            session_format.format_session_when(0.0, now=0.0)
        )

    s = _session(tmp_path)
    meta = s.meta
    for bad in (float("nan"), float("inf")):
        meta.updated_at = bad
        label = session_format.format_session_picker_label(meta)
        prompt, details = session_format.format_session_card(meta)
        assert "demo" in label and "p/m" in label
        assert "demo" in prompt and "p/m" in details


def test_mid_file_torn_row_keeps_the_surviving_prefix(kite_home: Path, tmp_path: Path) -> None:
    """Tearing is only 'normal' at EOF; a torn middle row must still not lose the rest."""
    s = _session(tmp_path, "multi")
    for i in range(4):
        s.append({"role": "user", "content": f"msg {i}"})
    path = s._session_path()

    lines = path.read_text(encoding="utf-8").split("\n")
    lines[2] = '{"type":"message","message":{"role":"user","content":"torn'
    path.write_text("\n".join(lines), encoding="utf-8")

    stats = scan_session_file(path)
    assert stats is not None
    assert stats.message_count == 4, "prefix and suffix rows must both survive a middle tear"
    assert [row["content"] for row in session_mod.load_session(s.id).messages] == [
        "multi", "msg 1", "msg 2", "msg 3",
    ]


def test_garbage_sidecars_never_break_meta_resolution(kite_home: Path, tmp_path: Path) -> None:
    """A garbage ``.meta`` / ``.stats.json`` degrades to file meta, never raises."""
    s = _session(tmp_path)
    sidecar = session_mod.sessions_dir() / f"{s.id}.meta"
    sidecar.write_text("}}not json{{", encoding="utf-8")
    assert session_mod.session_runtime_overlay(s._session_path()) == {}
    recovered = session_mod._read_session_meta(s._session_path())
    assert (recovered.id, recovered.task, recovered.provider) == (s.id, "demo", "p")

    from kite.memory.session_analytics import load_session_stats

    stats_path = session_mod.sessions_dir() / f"{s.id}.stats.json"
    for junk in ('{"tool_calls": "abc"}', '{"tool_calls": 5, "cost": "NaNish"}', "]]]"):
        stats_path.write_text(junk, encoding="utf-8")
        assert load_session_stats(s.id) is None


# --- 3. concurrency -----------------------------------------------------------


def test_checkpoint_writes_are_atomic_under_a_crash_during_replace(kite_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkpoint is the crash-recovery artifact — it must never be torn.

    ``save_checkpoint`` wrote with a plain ``write_text``. A crash (or a second
    process) mid-write leaves a half-written JSON file, and every later load of
    that checkpoint fails on parse — the safety net destroys the session it was
    meant to preserve. Asserting temp+replace semantics: when the replace step
    fails, the previous good checkpoint is still intact and parseable.
    """
    good = save_checkpoint(
        session_id="s-atomic", messages=[{"role": "user", "content": "first"}], cwd=str(tmp_path)
    )
    path = checkpoints_dir("s-atomic") / f"{good.id}.json"
    original = path.read_text(encoding="utf-8")
    before_files = set(path.parent.iterdir())

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        save_checkpoint(
            session_id="s-atomic", messages=[{"role": "user", "content": "second"}], cwd=str(tmp_path)
        )
    monkeypatch.setattr(os, "replace", real_replace)

    assert path.read_text(encoding="utf-8") == original, "checkpoint was left torn on disk"
    assert load_checkpoint("s-atomic", good.id).messages[0]["content"] == "first"
    assert set(path.parent.iterdir()) == before_files


def test_handoff_bundle_write_leaves_no_torn_artifact(kite_home: Path, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Handoff markdown/json are written atomically for the same reason."""
    s = create_session(task="handoff", cwd=str(workspace), provider="p", model="m")
    s.append({"role": "user", "content": "do the thing"})

    bundle = write_handoff(session=s, cwd=str(workspace))
    real_replace = os.replace
    for target in (bundle.markdown_path, bundle.json_path):
        original = target.read_bytes()
        leftovers = set(target.parent.glob("*.tmp"))

        def boom(src, dst, *, target=target):
            if Path(dst) == target:
                raise OSError("simulated handoff replace failure")
            return real_replace(src, dst)

        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", boom)
            with pytest.raises(OSError, match="handoff replace failure"):
                write_handoff(session=s, cwd=str(workspace))
        assert target.read_bytes() == original
        assert set(target.parent.glob("*.tmp")) == leftovers

    assert json.loads(bundle.json_path.read_text(encoding="utf-8"))["format"] == "kite-handoff-v1"


def test_mtime_ranking_never_runs_ahead_of_recorded_updated_at(kite_home: Path, tmp_path: Path) -> None:
    """``list_sessions`` prefilters on mtime, then orders by ``updated_at``.

    The prefilter is only sound if the mtime rank key (newest of transcript and
    sidecar mtime) is never *older* than the ``updated_at`` used for ordering —
    otherwise the bounded head can drop the session the picker should show.
    ``note_runtime`` stamps only the sidecar, so the sidecar leg is the one
    that actually carries "last touched".
    """
    for i in range(3):
        s = _session(tmp_path, f"task-{i}")
        s.note_runtime(model=f"m{i}")

    ranked = dict(session_mod._ranked_transcripts(session_mod.sessions_dir()))
    assert len(ranked) == 3
    for sid, mtime in ranked.items():
        meta = session_mod._read_session_meta(session_mod.sessions_dir() / f"{sid}.jsonl")
        assert meta is not None
        assert mtime >= meta.updated_at, (
            f"{sid}: mtime rank {mtime} < updated_at {meta.updated_at}; "
            "the bounded head could drop the newest session"
        )

    listed = [m.id for m in session_mod.list_sessions(limit=50)]
    assert len(listed) == 3
    # Ordering must agree with updated_at descending, not with insertion order.
    stamps = {m.id: m.updated_at for m in session_mod.list_sessions(limit=50)}
    assert listed == sorted(stamps, key=stamps.get, reverse=True)


# --- 4. store / episodic sqlite ----------------------------------------------


def test_corrupt_episodic_db_degrades_instead_of_killing_memory(kite_home: Path, workspace: Path, monkeypatch) -> None:
    """A corrupt episodes.sqlite must not take durable notes down with it.

    The observed failure was the worst shape: ``remember()`` persisted the note
    to MEMORY.md and *then* raised ``DatabaseError``, so the user was told the
    write failed when it had succeeded — and ``retrieve_for_prompt`` /
    ``render_for_prompt`` raised on every subsequent turn, permanently breaking
    the memory layer over a soft cache file.
    """
    store = MemoryStore(workspace)
    store.remember("warm the db")

    store.episodic.user_path().write_bytes(b"this is not a sqlite database" * 64)

    note = store.remember("the user prefers tabs over spaces")
    assert note.text == "the user prefers tabs over spaces"
    assert "the user prefers tabs over spaces" in {n.text for n in store.notes()}
    assert "the user prefers tabs over spaces" in store.retrieve_for_prompt("tabs spaces")
    assert "the user prefers tabs over spaces" in store.render_for_prompt()
    episode = store.record_episode(kind="note", summary="still recording")
    assert episode.summary == "still recording"
    assert "still recording" in {row.summary for row in store.episodes()}

    # A transient failure must not quarantine a healthy database and its WAL.
    from kite.memory import episodic

    path = store.episodic.user_path()
    original = path.read_bytes()
    quarantined = set(path.parent.glob("*.corrupt-*"))

    def busy(_path):
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as patch:
        patch.setattr(episodic, "_connect", busy)
        assert episodic._connect_or_quarantine(path) is None
    assert path.read_bytes() == original
    assert set(path.parent.glob("*.corrupt-*")) == quarantined


# A real second SQLite client waits until the contender reaches its INSERT.
# The brief overlap exercises SQLite's busy handler without a half-second stall.
_LOCK_HOLDER = """
import sqlite3, sys, time

conn = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=5)
conn.execute("BEGIN IMMEDIATE")
print("held", flush=True)
sys.stdin.readline()
time.sleep(0.01)
conn.rollback()
conn.close()
"""


def test_episodic_write_survives_a_concurrent_writer_holding_the_lock(kite_home: Path, workspace: Path, monkeypatch) -> None:
    """Two Kite processes on one KITE_HOME: a held lock must not lose an episode.

    ``PRAGMA busy_timeout`` plus WAL is the entire cross-process safety story for
    the episode log, so this asserts the final state: a competing process holds
    the write lock while we write, and every episode is still readable
    afterwards. Nothing asserts on elapsed time — only on data integrity.
    """
    import subprocess
    import sys

    from kite.memory import episodic

    store = EpisodicStore(workspace)
    for i in range(3):
        store.record(kind="note", summary=f"before {i}")
    contender = episodic._connect(store.user_path())

    holder = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER, str(store.user_path())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    def release_on_insert(statement):
        if statement.startswith("INSERT INTO episodes"):
            holder.stdin.write("release\n")
            holder.stdin.flush()

    contender.set_trace_callback(release_on_insert)
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held", "lock holder never took the lock"
        with monkeypatch.context() as patch:
            patch.setattr(episodic, "_connect", lambda _path: contender)
            store.record(kind="note", summary="during 0")
        for i in range(1, 3):
            store.record(kind="note", summary=f"during {i}")
    finally:
        contender.close()
        try:
            holder.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.communicate()
    assert holder.returncode == 0

    summaries = {e.summary for e in store.recent(limit=50)}
    assert {f"before {i}" for i in range(3)} <= summaries, "episodes lost before contention"
    assert {f"during {i}" for i in range(3)} <= summaries, "episodes lost during contention"

    conn = sqlite3.connect(str(store.user_path()))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_legacy_jsonl_migration_is_idempotent_after_a_crash_before_rename(kite_home: Path, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A crash between folding notes and renaming to ``.bak`` must not duplicate.

    The dedup compared the *raw* legacy text against the *clamped* stored text, so
    any note over ``MAX_MEMORY_NOTE_CHARS`` never matched its own copy. With the
    legacy file still on disk, the next launch re-folded it into a second
    identical note — and ``remember()`` was never called, so the duplication was
    invisible to the user.
    """
    memory_dir = kite_home / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    legacy = memory_dir / "notes.jsonl"
    long_note = "L" * 3000
    legacy.write_text(json.dumps({"id": "abc", "text": long_note}) + "\n", encoding="utf-8")

    semantic = SemanticStore(workspace)
    real_replace = os.replace

    def boom(src, dst):
        if str(dst).endswith(".bak"):
            raise OSError("simulated crash before rename to .bak")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", boom)
    _migrate_jsonl(semantic)
    monkeypatch.setattr(os, "replace", real_replace)
    assert legacy.is_file(), "fixture must simulate a crash that left the legacy file behind"

    _migrate_jsonl(semantic)  # the next launch re-reads the surviving legacy file

    texts = [n.text for n in semantic.notes(scope="user")]
    assert len(texts) == len(set(texts)), f"migration duplicated a note: {len(texts)} rows"
    assert len(texts) == 1

    _migrate_jsonl(semantic)  # fully settled: still idempotent
    assert len(semantic.notes(scope="user")) == 1


# --- 5. limits, coercion, ratios ---------------------------------------------


def test_limit_zero_or_negative_means_no_rows(kite_home: Path, tmp_path: Path) -> None:
    """A 0/negative limit must mean 'nothing', never 'everything' or a tail slice."""
    for i in range(2):
        save_checkpoint(session_id="s-lim", messages=[{"role": "user", "content": str(i)}], cwd=str(tmp_path))
    assert list_checkpoints("s-lim", limit=0) == []
    assert list_checkpoints("s-lim", limit=-2) == []

    log = AuditLog()
    for i in range(5):
        log.append("tool", tool=f"t{i}", ok=True)
    assert log.tail(0) == []
    assert log.tail(-1) == []
    assert len(log.tail(3)) == 3


def test_working_style_observation_tolerates_non_numeric_model_stats(kite_home: Path, workspace: Path) -> None:
    """Model stats reach us as provider payloads; a string must not crash the turn.

    ``observe_session_turn`` is called at the end of every REPL turn purely to
    record a soft signal. ``int("abc")`` escaping there aborts the turn's
    post-processing on nothing but a cosmetic observation.
    """
    store = MemoryStore(workspace)
    for junk in ({"api_calls": "abc"}, {"model_stats": {"api_calls": "many"}}, {"api_calls": None}):
        assert observe_session_turn(store, session_id="s", extra=junk) == 0
    assert store.episodes() == []

    assert observe_session_turn(
        store, session_id="s", extra={"model_stats": {"write_edits": "6", "api_calls": "2"}}
    ) == 1
    assert [(row.kind, row.summary) for row in store.episodes()] == [
        ("style", "iterates with several edits in one sitting"),
    ]


def test_dashboard_average_is_safe_with_no_sessions(kite_home: Path) -> None:
    """The avg divides by len(sessions) — zero rows must not raise ZeroDivisionError."""
    from kite.memory.session_analytics import build_dashboard_summary

    summary = build_dashboard_summary(limit=0)
    assert summary.session_count == 0
    assert summary.avg_duration_s == 0.0
