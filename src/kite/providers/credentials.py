"""Secure API key storage in ~/.kite/.env — shared by setup, CLI, and REPL."""

from __future__ import annotations

import getpass
import os
import re
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from kite.config import UserConfig, ensure_home, kite_home
from kite.providers.catalog import load_catalog
from kite.providers.keys import api_key_env_names, api_key_for

if TYPE_CHECKING:
    from rich.console import Console


def env_file_path() -> Path:
    ensure_home()
    return kite_home() / ".env"


def load_kite_env() -> None:
    """Load project .env then ~/.kite/.env.

    Non-empty project values win. Kite home fills keys still unset or left
    empty (``KEY=`` placeholders from a copied ``.env.example``).
    """
    from dotenv import dotenv_values, load_dotenv

    project_env = Path.cwd() / ".env"
    if project_env.is_file():
        load_dotenv(project_env)
    path = env_file_path()
    if not path.is_file():
        return
    for key, val in dotenv_values(path).items():
        if not val:
            continue
        if not (os.getenv(key) or "").strip():
            os.environ[key] = val


def read_env_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _format_env_value(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if any(ch in text for ch in " #\t\n\r\"'\\"):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _secure_env_file(path: Path) -> None:
    """Owner read/write only — best effort on each platform."""
    if not path.is_file():
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if os.name == "nt":
        try:
            import subprocess

            user = os.getenv("USERNAME") or os.getenv("USER") or ""
            if user:
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                    check=False,
                    capture_output=True,
                )
        except Exception:
            pass


def write_api_key(env_var: str, value: str) -> Path:
    """Set or replace one env var in ~/.kite/.env without touching other keys."""
    secret = value.strip()
    if not secret:
        raise ValueError("API key cannot be empty")
    path = env_file_path()
    lines = read_env_lines(path)
    pattern = re.compile(rf"^\s*{re.escape(env_var)}\s*=")
    new_line = f"{env_var}={_format_env_value(secret)}"
    replaced = False
    out: list[str] = []
    for line in lines:
        if pattern.match(line):
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"# {env_var}")
        out.append(new_line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    _secure_env_file(path)
    os.environ[env_var] = secret
    return path


def remove_api_key(env_var: str) -> bool:
    """Drop one env var from ~/.kite/.env and the current process."""
    path = env_file_path()
    pattern = re.compile(rf"^\s*{re.escape(env_var)}\s*=")
    comment = f"# {env_var}"
    removed = False
    if path.is_file():
        out: list[str] = []
        for line in read_env_lines(path):
            if pattern.match(line):
                removed = True
                continue
            if removed and line.strip() == comment:
                continue
            out.append(line)
        if removed:
            if out:
                text = "\n".join(out).rstrip() + "\n"
                path.write_text(text, encoding="utf-8")
                _secure_env_file(path)
            else:
                path.unlink(missing_ok=True)
    os.environ.pop(env_var, None)
    return removed


def read_secret(prompt: str) -> str | None:
    """Hidden stdin read — never echoes the key."""
    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import prompt as pt_prompt

        return pt_prompt(prompt, is_password=True).strip()
    except Exception:
        pass
    try:
        return getpass.getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def configured_providers() -> list[tuple[str, bool, str]]:
    catalog = load_catalog()
    rows: list[tuple[str, bool, str]] = []
    for spec in catalog.list():
        if spec.name == "ollama":
            rows.append((spec.name, True, "local"))
            continue
        envs = api_key_env_names(spec)
        if not envs:
            rows.append((spec.name, False, "—"))
            continue
        ok = bool(api_key_for(spec))
        rows.append((spec.name, ok, envs[0]))
    return rows


def resolve_provider_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    if not name:
        raise KeyError("provider name required")
    return load_catalog().get(name).name


def loginable_providers() -> list[tuple[str, str, str]]:
    """(name, display_name, primary_env) for providers that accept API keys."""
    rows: list[tuple[str, str, str]] = []
    for spec in load_catalog().list():
        if spec.name == "ollama":
            continue
        envs = api_key_env_names(spec)
        if not envs:
            continue
        rows.append((spec.name, spec.display_name, envs[0]))
    return rows


def login_provider(
    provider: str,
    *,
    set_default: bool = False,
    console: Console | None = None,
) -> tuple[int, str, str | None]:
    """Prompt for a key and save to ~/.kite/.env. Returns (exit_code, message, provider_name)."""
    catalog = load_catalog()
    try:
        resolved = resolve_provider_name(provider)
        spec = catalog.get(resolved)
    except KeyError as e:
        return 2, str(e), None

    if spec.name == "ollama":
        return 0, "ollama is local — no API key needed", spec.name

    env_names = api_key_env_names(spec)
    if not env_names:
        return 0, f"{spec.display_name} does not use an API key", spec.name

    primary = env_names[0]
    path = env_file_path()

    if console is not None:
        console.print(f"[dim]{spec.display_name}[/]  →  [cyan]{path}[/]")
        if spec.docs_url:
            console.print(f"[dim]Get a key:[/] {spec.docs_url}")
        if api_key_for(spec):
            console.print(f"[dim]Replacing existing {primary}[/]")

    secret = read_secret(f"{primary} (hidden): ")
    if secret is None:
        return 130, "cancelled", None
    if not secret:
        return 2, "empty key — nothing saved", None

    saved = write_api_key(primary, secret)
    for alias in env_names[1:]:
        remove_api_key(alias)

    msg = f"saved {primary} → {saved}"
    if set_default:
        cfg = UserConfig.load()
        cfg.default_provider = spec.name
        cfg.save()
        msg += f"  ·  default provider → {spec.name}"

    return 0, msg, spec.name


def logout_provider(provider: str) -> tuple[int, str]:
    try:
        resolved = resolve_provider_name(provider)
        spec = load_catalog().get(resolved)
    except KeyError as e:
        return 2, str(e)

    if spec.name == "ollama":
        return 0, "ollama has no stored key"

    env_names = api_key_env_names(spec)
    if not env_names:
        return 0, f"{spec.display_name} does not use an API key"

    removed_any = False
    for env_var in env_names:
        if remove_api_key(env_var):
            removed_any = True

    if removed_any:
        return 0, f"removed {env_names[0]} from {env_file_path()}"
    return 0, f"no key on file for {spec.name} ({env_names[0]})"
