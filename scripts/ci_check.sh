#!/usr/bin/env bash
## [Unreleased]

### Added
- Full benchmark baselines/comparison and runtime tracing: see [`kite bench`](kite_commands.md#harness-timing-kite-bench) and [`KITE_TRACE_JSONL`](kite_commands.md#runtime-event-tracing).
- Isolated worktrees, fast gates, offline end-to-end QA, and CLI profiling: see [contributor workflows](CONTRIBUTING.md#fast-isolated-agent-loops).

### Changed
Representative before/after measurements from controlled optimization runs (not portable timing guarantees):
- Streaming answer processing ~13 → 4.6 µs/chunk; reasoning accumulation 119 → 0.42 µs/chunk at 80k events.
- `import kite.ui` 30 → 0.2 ms; configured model resolution 546 → 72 ms cold; `LitellmModel` construction 1.15 s → approximately zero; headless time-to-first-query ~1.9 → 0.6 s.
- Path completion on 10k files 34 → 4 ms; picker on 10k options 166 → 35 ms; directory sketch on 20k files 68 → 4 ms; grep benchmark ~26 → 7 ms.
- Redaction of 5 MB plain text 300 → 30 ms; `ProcessRunner` peak memory for 200 MiB of output 525 → 1.3 MB.
- Agent-loop accounting at 200 turns 0.39 → 0.27 ms/turn.
- Session tail resume with a single 50 MB row 7.4 s → 75 ms; recent-event reads 41 → 0.05 ms; semantic-memory rendering 16 → 2 ms.
- Warm development install 0.77 → 0.12 s; see [locked development installs](CONTRIBUTING.md#how-to-set-up).
- Startup/import boundaries, model capabilities, context/history processing, and session internals: see [architecture.md](architecture.md).
- Named behavioral tests replace count-driven batching; see the [test policy and dev loop](AGENTS.md#tests--ci).

### Fixed
- CLI/REPL rendering, completion, jobs, session recovery, and verification behavior: see [kite_commands.md](kite_commands.md).
- Prompt-history correctness and episodic-store lock handling: see [architecture.md](architecture.md#startup-and-request-work) and [context & memory](architecture.md#context--memory).

### Security
- Bounded output capture, redaction-before-truncation, private trace files, and durable atomic writes: see [SECURITY.md](SECURITY.md).

## [1.0.7] - 2026-10-09

### Added
- Offline end-to-end smoke coverage exercising the real CLI with a loopback recorded provider; isolated worktrees; faster CI tooling; and CLI profiling.
- `KITE_TRACE_JSONL` opt-in redacted JSONL runtime tracing.
- `kite bench --suite full` with 43 measurements and MAD-aware `--save` / `--compare`.

### Changed
- Runtime hot paths improve model construction, headless startup, streaming, reasoning accumulation, completion/picker performance, and large transcript/session operations.
- Test suite refactored into named, isolated tests with deterministic fixtures and no external network calls.

### Fixed
- Prompt-cache stale history, missing repository symbol maps, and narrow-terminal stream boundary/width handling.
- Session recovery, transient SQLite lock handling, resume exit codes, background-job watchdogs, shell output limits, pre-truncation secret redaction, interpreter selection, and invalid task argument prewarm.
- Test environment leakage that could trigger real external provider requests.
- Added developer workflow documentation for performance/behavior changes, runtime traces, and test policy.
set -euo pipefail
RELEASE=0
FAST=0
if [[ "${1:-}" == "--release" ]]; then
  RELEASE=1
  shift
fi
if [[ "${1:-}" == "--fast" ]]; then
  FAST=1
  shift
elif [[ $# -gt 0 ]]; then
  echo "Usage: scripts/ci_check.sh [--release] [--fast [--base REF | --files PATH...]]" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export KITE_SKIP_SETUP="${KITE_SKIP_SETUP:-1}"
export KITE_TYPED_PICK="${KITE_TYPED_PICK:-1}"
if [[ -z "${KITE_HOME:-}" ]]; then
  KITE_HOME="$(mktemp -d "${TMPDIR:-/tmp}/kite-ci-home.XXXXXX")"
  export KITE_HOME
  trap 'rm -rf "$KITE_HOME"' EXIT
fi
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  elif [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then
    PYTHON="$ROOT/.venv/Scripts/python.exe"
  else
    PYTHON="python3"
  fi
fi
echo "Using Python: $PYTHON"
echo "== sync_version --check"
if [[ "$RELEASE" == "1" ]]; then
  "$PYTHON" scripts/sync_version.py --check --release
else
  "$PYTHON" scripts/sync_version.py --check
fi
if [[ "$FAST" == "1" ]]; then
  "$PYTHON" scripts/ci_fast.py "$@"
else
  echo "== ruff"
  "$PYTHON" -m ruff check src tests scripts
  echo "== pytest"
  "$PYTHON" -m pytest -q --tb=short -p faulthandler
fi
echo "== kite bench --check"
"$PYTHON" -m kite.cli.run bench --check
if [[ "$FAST" == "1" ]]; then
  echo "Fast gates ok (run full ci_check.sh before merging)"
else
  echo "CI gates ok"
fi
