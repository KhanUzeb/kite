#!/usr/bin/env bash
# kite-release-version: 0.8.1
# Install Kite on macOS/Linux: clone (optional), venv, editable install, env bootstrap.
set -euo pipefail

REPO_URL="${KITE_REPO_URL:-https://github.com/KhanUzeb/kite.git}"
PYTHON="${KITE_PYTHON:-3.12}"
INSTALL_DIR="${KITE_INSTALL_DIR:-}"
SKIP_CLONE=0
DEV_EXTRAS=1
VERIFY=0
RUN_SETUP=0

usage() {
  cat <<'EOF'
Usage: ./scripts/install.sh [options]

Options:
  --dir PATH       Install directory (default: current repo or ~/kite)
  --repo URL       Git remote to clone (default: KhanUzeb/kite on GitHub)
  --python VER     Python version for uv venv (default: 3.12)
  --no-clone       Skip git clone; install from the current directory
  --no-dev         Install runtime deps only (omit pytest dev extra)
  --verify         Run pytest after install (dev / CI smoke check)
  --setup          Run `kite setup` after install (interactive TTY only)
  -h, --help       Show this help

Examples:
  git clone https://github.com/KhanUzeb/kite.git && cd kite && ./scripts/install.sh
  curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.sh | bash
  KITE_INSTALL_DIR=~/tools/kite ./scripts/install.sh
  ./scripts/install.sh --no-clone --verify
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    --no-clone) SKIP_CLONE=1; shift ;;
    --no-dev) DEV_EXTRAS=0; shift ;;
    --verify) VERIFY=1; shift ;;
    --setup) RUN_SETUP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

ensure_uv() {
  if have uv; then
    return
  fi
  echo "uv not found — installing via official installer..."
  curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
  if ! have uv; then
    echo "uv install finished but 'uv' is still not on PATH." >&2
    echo "Add ~/.local/bin to PATH, open a new shell, and re-run this script." >&2
    exit 1
  fi
}

repo_root_from_script() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/.." && pwd
}

bootstrap_kite_home() {
  local env_file="${KITE_HOME}/.env"
  if [[ ! -f "${env_file}" ]] && [[ -f "${INSTALL_DIR}/.env.example" ]]; then
    cp "${INSTALL_DIR}/.env.example" "${env_file}"
    chmod 600 "${env_file}" 2>/dev/null || true
    echo "Created ${env_file} (template) — run: kite setup"
  elif [[ -f "${env_file}" ]]; then
    chmod 600 "${env_file}" 2>/dev/null || true
  fi
  python -c "from kite.config import ensure_home; ensure_home()"
}

if [[ -z "${INSTALL_DIR}" ]]; then
  if [[ "${SKIP_CLONE}" -eq 1 ]] || [[ -f "$(repo_root_from_script)/pyproject.toml" ]]; then
    INSTALL_DIR="$(repo_root_from_script)"
    SKIP_CLONE=1
  else
    INSTALL_DIR="${HOME}/kite"
  fi
fi

mkdir -p "$(dirname "${INSTALL_DIR}")"

if [[ "${SKIP_CLONE}" -eq 0 ]]; then
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    echo "Repo already exists at ${INSTALL_DIR} — pulling latest..."
    git -C "${INSTALL_DIR}" pull --ff-only
  else
    echo "Cloning ${REPO_URL} → ${INSTALL_DIR}"
    git clone "${REPO_URL}" "${INSTALL_DIR}"
  fi
fi

if [[ ! -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  echo "No pyproject.toml in ${INSTALL_DIR}. Use --dir or run from a kite checkout." >&2
  exit 1
fi

ensure_uv
cd "${INSTALL_DIR}"

echo "Creating venv (.venv) with Python ${PYTHON}..."
if [[ -d .venv ]]; then
  echo "Using existing .venv"
else
  uv venv --python "${PYTHON}" .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [[ "${DEV_EXTRAS}" -eq 1 ]]; then
  uv pip install -e ".[dev]"
else
  uv pip install -e .
fi

export KITE_HOME="${KITE_HOME:-${HOME}/.kite}"
mkdir -p "${KITE_HOME}"
bootstrap_kite_home

KITE_VERSION="$(kite --version 2>/dev/null || true)"
if [[ -z "${KITE_VERSION}" ]]; then
  echo "Warning: kite CLI not on PATH in this shell. Activate .venv first." >&2
else
  echo "Installed kite ${KITE_VERSION}"
fi

if [[ "${VERIFY}" -eq 1 ]]; then
  echo "Running pytest (smoke check)..."
  pytest -q
fi

if [[ "${RUN_SETUP}" -eq 1 ]] && [[ -t 0 ]] && [[ -t 1 ]]; then
  echo ""
  echo "Starting kite setup (Ctrl+C to skip)..."
  kite setup || true
fi

VENV_BIN="${INSTALL_DIR}/.venv/bin"
cat <<EOF

Kite installed in: ${INSTALL_DIR}
Kite home:         ${KITE_HOME}

Activate this shell:
  source "${VENV_BIN}/activate"

Use kite from any project directory (workspace = current directory):
  cd /path/to/your/project
  kite
  kite run "summarize this repo"
  kite chat --cwd /path/to/other/project

Or target a directory explicitly:
  kite run --cwd /path/to/project "add tests"

Make kite available in every new shell (add to ~/.bashrc or ~/.zshrc):
  export PATH="${VENV_BIN}:\$PATH"

First run (recommended):
  kite setup                 # guided API key + model picker (or ./scripts/install.sh --setup)
  kite providers             # readiness + credential status
  kite models -p groq --select
  kite runtime-config

REPL tips (after kite setup):
  /plan /build               plan vs apply mode
  /setup /login              credentials and model
  /checkpoint /handoff       save or export session context
  /compact                   summarize older turns
  Ctrl+C                     interrupt current turn (REPL stays open)
  Ctrl+O / Ctrl+P / Ctrl+B   expand tools / plan / build

Contributors: pytest  ·  optional: ./scripts/install.sh --verify
Docs: ${INSTALL_DIR}/README.md  ·  ${INSTALL_DIR}/kite_commands.md
EOF
