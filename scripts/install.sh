#!/usr/bin/env bash
# kite-release-version: 0.9.6
# Install Kite as a global CLI (default) or editable checkout (--dev).
#
# Compatible with: macOS (bash 3.2+), Ubuntu/Debian Linux, WSL, other Unix.
# End-user (any directory):
#   curl -fsSL …/install.sh | bash
#   → uv tool install from git + PATH; then `cd any/project && kite`
#
# Contributor (this repo):
#   ./scripts/install.sh --dev
set -euo pipefail

REPO_URL="${KITE_REPO_URL:-https://github.com/KhanUzeb/kite.git}"
REPO_REF="${KITE_REPO_REF:-main}"
PYTHON="${KITE_PYTHON:-3.12}"
INSTALL_DIR="${KITE_INSTALL_DIR:-}"
DEV_MODE=0
GLOBAL_MODE=0
SKIP_CLONE=0
DEV_EXTRAS=1
VERIFY=0
RUN_SETUP=0
FORCE=0

usage() {
  cat <<'EOF'
Usage: ./scripts/install.sh [options]

Default: install the kite CLI via `uv tool install` so opening `kite` turns
its environment on automatically (you never manually activate a kite venv).
In a project that has .venv, kite also auto-uses that for python/pip tools.

Options:
  --global         Same as default (CLI on PATH)
  --dev            Editable CLI from a kite checkout (+ local .venv for pytest)
  --dir PATH       Checkout path for --dev (default: this repo or ~/kite)
  --repo URL       Git remote (default: KhanUzeb/kite on GitHub)
  --ref REF        Git branch/tag/commit for tool install (default: main)
  --python VER     Python version for uv (default: 3.12)
  --no-clone       With --dev: install from existing checkout only
  --no-dev         With --dev: omit pytest extra in local .venv
  --force          Reinstall / overwrite existing kite tool entry
  --verify         Run pytest after --dev install
  --setup          Run `kite setup` after install (interactive TTY only)
  -h, --help       Show this help

Examples:
  curl -fsSL https://raw.githubusercontent.com/KhanUzeb/kite/main/scripts/install.sh | bash
  curl -fsSL …/download.sh | bash -s -- --setup
  ./scripts/install.sh --dev
  ./scripts/install.sh --global --force
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --global) GLOBAL_MODE=1; DEV_MODE=0; shift ;;
    --dev) DEV_MODE=1; GLOBAL_MODE=0; shift ;;
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --ref) REPO_REF="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    --no-clone) SKIP_CLONE=1; DEV_MODE=1; GLOBAL_MODE=0; shift ;;
    --no-dev) DEV_EXTRAS=0; shift ;;
    --force) FORCE=1; shift ;;
    --verify) VERIFY=1; DEV_MODE=1; GLOBAL_MODE=0; shift ;;
    --setup) RUN_SETUP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

os_family() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin*) echo darwin ;;
    Linux*) echo linux ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    *) echo other ;;
  esac
}

hint_install_deps() {
  local os
  os="$(os_family)"
  echo "Install missing tools, then re-run:" >&2
  case "${os}" in
    darwin)
      echo "  xcode-select --install    # provides git + curl" >&2
      ;;
    linux)
      if have apt-get; then
        echo "  sudo apt-get update && sudo apt-get install -y curl git ca-certificates" >&2
      elif have dnf; then
        echo "  sudo dnf install -y curl git ca-certificates" >&2
      elif have yum; then
        echo "  sudo yum install -y curl git ca-certificates" >&2
      elif have pacman; then
        echo "  sudo pacman -S --needed curl git ca-certificates" >&2
      else
        echo "  Install curl, git, and CA certificates via your package manager." >&2
      fi
      ;;
    *)
      echo "  Need: curl, git, and a working network." >&2
      ;;
  esac
}

preflight() {
  local missing=0
  if ! have curl; then
    echo "curl is required but not found." >&2
    missing=1
  fi
  if ! have git; then
    echo "git is required (uv installs kite from GitHub)." >&2
    missing=1
  fi
  if [[ "${missing}" -ne 0 ]]; then
    hint_install_deps
    exit 1
  fi
  # Home must be writable for ~/.local, ~/.kite, uv tool dirs
  if [[ -z "${HOME:-}" ]] || [[ ! -w "${HOME}" ]]; then
    echo "\$HOME must be set and writable (got: ${HOME:-unset})." >&2
    exit 1
  fi
}

refresh_uv_path() {
  # Cover official uv install locations across macOS / Linux / older cargo installs.
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  if [[ -n "${XDG_BIN_HOME:-}" ]]; then
    export PATH="${XDG_BIN_HOME}:${PATH}"
  fi
  if [[ -n "${XDG_DATA_HOME:-}" ]]; then
    export PATH="${XDG_DATA_HOME}/../bin:${PATH}"
  fi
}

ensure_uv() {
  refresh_uv_path
  if have uv; then
    return
  fi
  echo "uv not found — installing via official installer..."
  # Official installer is unsigned shell; pipe to sh is the supported path (same as Astral docs).
  curl -fsSL https://astral.sh/uv/install.sh | sh
  refresh_uv_path
  if ! have uv; then
    echo "uv install finished but 'uv' is still not on PATH." >&2
    echo "Add ~/.local/bin to PATH, open a new shell, and re-run this script." >&2
    hint_install_deps
    exit 1
  fi
}

# True when fed via curl|bash / mktemp — never treat CWD as the kite repo.
is_ephemeral_script() {
  local src="${BASH_SOURCE[0]:-}"
  [[ -z "${src}" ]] && return 0
  case "${src}" in
    /dev/fd/*|/proc/self/fd/*) return 0 ;;
    */tmp/*|*/Temp/*|*kite-install*|*/var/folders/*) return 0 ;;
  esac
  return 1
}

repo_root_from_script() {
  local script_dir
  if is_ephemeral_script; then
    return 1
  fi
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/.." && pwd
}

is_kite_checkout() {
  local root="$1"
  [[ -f "${root}/pyproject.toml" ]] || return 1
  grep -qE '^name[[:space:]]*=[[:space:]]*"kite"' "${root}/pyproject.toml" 2>/dev/null
}

git_tool_spec() {
  local url="${REPO_URL%.git}"
  echo "git+${url}.git@${REPO_REF}"
}

append_path_line() {
  local file="$1"
  local line="$2"
  [[ -z "${file}" ]] && return 0
  touch "${file}" 2>/dev/null || return 0
  if grep -Fqs "${line}" "${file}" 2>/dev/null; then
    return 0
  fi
  printf '\n# kite / uv tool\n%s\n' "${line}" >> "${file}"
}

ensure_tool_path() {
  local bin_dir=""
  local line=""
  bin_dir="$(uv tool dir --bin 2>/dev/null || true)"
  if [[ -n "${bin_dir}" ]]; then
    export PATH="${bin_dir}:${PATH}"
    line="export PATH=\"${bin_dir}:\$PATH\""
  fi

  # Prefer uv's own shell updater (bash/zsh/fish/powershell profiles).
  if uv tool update-shell >/dev/null 2>&1; then
    echo "Ensured uv tool bin is on PATH (open a new terminal if kite is not found)."
    return 0
  fi

  # Fallback: append to common Unix profiles (macOS zsh default, Ubuntu bash).
  if [[ -n "${line}" ]]; then
    case "$(basename "${SHELL:-bash}")" in
      zsh) append_path_line "${HOME}/.zshrc" "${line}" ;;
      bash) append_path_line "${HOME}/.bashrc" "${line}"; append_path_line "${HOME}/.profile" "${line}" ;;
      fish)
        mkdir -p "${HOME}/.config/fish"
        append_path_line "${HOME}/.config/fish/config.fish" "fish_add_path ${bin_dir}"
        ;;
      *)
        append_path_line "${HOME}/.profile" "${line}"
        append_path_line "${HOME}/.bashrc" "${line}"
        append_path_line "${HOME}/.zshrc" "${line}"
        ;;
    esac
    echo "Added uv tool bin to your shell profile. Open a new terminal, or run:"
    echo "  ${line}"
  fi
}

bootstrap_kite_home() {
  local env_file="${KITE_HOME}/.env"
  local example=""
  if [[ -n "${INSTALL_DIR:-}" && -f "${INSTALL_DIR}/.env.example" ]]; then
    example="${INSTALL_DIR}/.env.example"
  fi
  mkdir -p "${KITE_HOME}"
  if [[ ! -f "${env_file}" ]] && [[ -n "${example}" ]]; then
    cp "${example}" "${env_file}"
    chmod 600 "${env_file}" 2>/dev/null || true
    echo "Created ${env_file} (template) — run: kite setup"
  elif [[ -f "${env_file}" ]]; then
    chmod 600 "${env_file}" 2>/dev/null || true
  fi
  python -c "from kite.config import ensure_home; ensure_home()" 2>/dev/null || true
}

install_global_cli() {
  ensure_uv
  local spec
  local tool_python=""
  local ver=""
  spec="$(git_tool_spec)"
  echo "Installing kite CLI globally from ${spec}..."
  echo "(isolated tool env — not cloning into your current directory)"

  # Avoid empty-array expansion (breaks macOS /bin/bash 3.2 with set -u).
  set +e
  if [[ "${FORCE}" -eq 1 ]]; then
    uv tool install --python "${PYTHON}" --force "${spec}"
    rc=$?
  else
    uv tool install --python "${PYTHON}" "${spec}"
    rc=$?
    if [[ "${rc}" -ne 0 ]]; then
      echo "Retrying with --force (kite may already be installed)..."
      uv tool install --python "${PYTHON}" --force "${spec}"
      rc=$?
    fi
  fi
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    echo "uv tool install failed." >&2
    echo "Check network access to GitHub and that git works: git ls-remote ${REPO_URL}" >&2
    exit 1
  fi

  ensure_tool_path

  export KITE_HOME="${KITE_HOME:-${HOME}/.kite}"
  mkdir -p "${KITE_HOME}"

  tool_python="$(uv tool dir 2>/dev/null)/kite/bin/python" || true
  if [[ -x "${tool_python:-}" ]]; then
    "${tool_python}" -c "from kite.config import ensure_home; ensure_home()" 2>/dev/null || true
  fi

  ver="$(kite --version 2>/dev/null || true)"
  if [[ -z "${ver}" ]]; then
    echo "Warning: kite not on PATH in this shell yet." >&2
    echo "Open a new terminal, or: export PATH=\"\$(uv tool dir --bin):\$PATH\"" >&2
  else
    echo "Installed ${ver}"
  fi

  if [[ "${RUN_SETUP}" -eq 1 ]] && [[ -t 0 ]] && [[ -t 1 ]]; then
    echo ""
    echo "Starting kite setup (Ctrl+C to skip)..."
    kite setup || true
  fi

  cat <<EOF

Kite CLI is on PATH (uv tool). Opening \`kite\` turns its environment on —
you do not activate anything first.

Kite home: ${KITE_HOME}
OS:        $(uname -s) ($(os_family))

Use from any project (workspace = cwd; project .venv auto-used for tools):
  cd /path/to/your/project
  kite
  kite run "summarize this repo"

First run (recommended):
  kite setup
  kite providers
  kite models -p groq --select

Update later:   uv tool upgrade kite
Uninstall:      uv tool uninstall kite
Hacking on kite source: ./scripts/install.sh --dev
EOF
}

install_dev_editable() {
  local root=""
  local ver=""

  if [[ -z "${INSTALL_DIR}" ]]; then
    if root="$(repo_root_from_script)" && is_kite_checkout "${root}"; then
      INSTALL_DIR="${root}"
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
      echo "Cloning ${REPO_URL} → ${INSTALL_DIR} (dev checkout)"
      git clone "${REPO_URL}" "${INSTALL_DIR}"
    fi
  fi

  if ! is_kite_checkout "${INSTALL_DIR}"; then
    echo "No kite pyproject.toml in ${INSTALL_DIR}. Use --dir or run from a kite checkout." >&2
    exit 1
  fi

  ensure_uv
  cd "${INSTALL_DIR}"

  # Editable CLI on PATH — opening `kite` uses this checkout; no activate needed.
  echo "Installing editable kite CLI on PATH (uv tool --editable)..."
  set +e
  uv tool install --python "${PYTHON}" --force --editable "${INSTALL_DIR}"
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    echo "uv tool install --editable failed." >&2
    exit 1
  fi
  ensure_tool_path

  # Local .venv is only for pytest / IDE; not required to open kite.
  echo "Creating contributor .venv for pytest (optional; kite CLI already on PATH)..."
  if [[ ! -d .venv ]]; then
    uv venv --python "${PYTHON}" .venv
  fi
  if [[ "${DEV_EXTRAS}" -eq 1 ]]; then
    uv pip install --python .venv/bin/python -e ".[dev]"
  else
    uv pip install --python .venv/bin/python -e .
  fi

  export KITE_HOME="${KITE_HOME:-${HOME}/.kite}"
  mkdir -p "${KITE_HOME}"
  bootstrap_kite_home

  ver="$(kite --version 2>/dev/null || true)"
  if [[ -z "${ver}" ]]; then
    echo "Warning: kite not on PATH in this shell yet." >&2
    echo "Open a new terminal, or: export PATH=\"\$(uv tool dir --bin):\$PATH\"" >&2
  else
    echo "Installed ${ver} (editable on PATH — opening kite turns env on)"
  fi

  if [[ "${VERIFY}" -eq 1 ]]; then
    echo "Running pytest (smoke check)..."
    # Prefer venv pytest without requiring shell activate
    if [[ -x .venv/bin/pytest ]]; then
      .venv/bin/pytest -q
    else
      uv run --python .venv pytest -q
    fi
  fi

  if [[ "${RUN_SETUP}" -eq 1 ]] && [[ -t 0 ]] && [[ -t 1 ]]; then
    echo ""
    echo "Starting kite setup (Ctrl+C to skip)..."
    kite setup || true
  fi

  cat <<EOF

Dev checkout: ${INSTALL_DIR}
Kite home:    ${KITE_HOME}

Opening \`kite\` uses this editable install (env on automatically).
Local .venv is only for pytest/IDE — you do not need to activate it to run kite.

  kite
  .venv/bin/pytest -q

Update / uninstall: uv tool upgrade kite · uv tool uninstall kite
EOF
}

preflight

if [[ "${DEV_MODE}" -eq 1 ]]; then
  install_dev_editable
else
  install_global_cli
fi
