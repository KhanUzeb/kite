"""Non-blocking GitHub release check — notify when a newer Kite version exists."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from kite.config.user import ensure_home, kite_home

_GITHUB_REPO = "KhanUzeb/kite"
_CACHE_FILE = "release_check.json"
_CACHE_TTL_SECONDS = 24 * 3600
_OFFLINE = os.getenv("KITE_OFFLINE", "").strip().lower() in {"1", "true", "yes"}


def _parse_version(text: str) -> tuple[int, ...]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _cache_path() -> Path:
    return kite_home() / _CACHE_FILE


def _read_cache() -> dict | None:
    path = _cache_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_cache(payload: dict) -> None:
    ensure_home()
    _cache_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fetch_latest_release() -> dict | None:
    from kite import __version__

    url = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"kite/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def check_for_update(*, force: bool = False) -> str | None:
    """Return a short flash message when GitHub has a newer release, else None."""
    if _OFFLINE:
        return None
    from kite import __version__

    now = time.time()
    cached = _read_cache()
    if not force and cached:
        checked_at = float(cached.get("checked_at") or 0)
        if now - checked_at < _CACHE_TTL_SECONDS:
            latest = str(cached.get("latest") or "")
            if latest and _parse_version(latest) > _parse_version(__version__):
                return _format_message(__version__, latest, str(cached.get("url") or ""))
            return None

    data = _fetch_latest_release()
    if not data:
        return None

    tag = str(data.get("tag_name") or "").lstrip("v")
    html_url = str(data.get("html_url") or f"https://github.com/{_GITHUB_REPO}/releases/latest")
    _write_cache(
        {
            "checked_at": now,
            "latest": tag,
            "url": html_url,
        }
    )
    if tag and _parse_version(tag) > _parse_version(__version__):
        return _format_message(__version__, tag, html_url)
    return None


def _format_message(current: str, latest: str, url: str) -> str:
    base = f"Kite v{latest} is out (you have v{current})"
    if url:
        return f"{base} — {url}"
    return base


def schedule_release_check(callback) -> None:
    """Run release check in a daemon thread; invoke callback(message|None) on the main thread."""

    def _work() -> None:
        msg = check_for_update()
        if callback is not None:
            try:
                callback(msg)
            except Exception:
                pass

    threading.Thread(target=_work, daemon=True, name="kite-release-check").start()
