"""Project context discovery cache."""

from __future__ import annotations

import time

import kite.context.discovery as discovery
from kite.context.discovery import gather_project_context


def test_context_cache_returns_same_object(workspace, monkeypatch) -> None:
    monkeypatch.setattr(discovery, "_CTX_CACHE", {})
    monkeypatch.setattr(discovery, "_CTX_TTL_SECONDS", 60.0)

    first = gather_project_context(workspace, include_git=False)
    second = gather_project_context(workspace, include_git=False)
    assert first is second


def test_context_cache_expires(workspace, monkeypatch) -> None:
    monkeypatch.setattr(discovery, "_CTX_CACHE", {})
    monkeypatch.setattr(discovery, "_CTX_TTL_SECONDS", 0.01)

    first = gather_project_context(workspace, include_git=False)
    time.sleep(0.02)
    second = gather_project_context(workspace, include_git=False)
    assert first is not second
