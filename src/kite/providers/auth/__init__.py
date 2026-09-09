"""BYOS auth provider registry."""

from __future__ import annotations

from kite.providers.auth.base import AuthProvider
from kite.providers.auth.claude import ClaudeCodeAuthProvider
from kite.providers.auth.codex import CodexAuthProvider
from kite.providers.auth.grok import GrokCliAuthProvider

# Login/logout aliases (subscription shorthand).
LOGIN_ALIASES: dict[str, str] = {
    "codex": "chatgpt",
    "chatgpt-sub": "chatgpt",
    "claude-sub": "claude",
    "grok-sub": "grok",
    "xai": "grok",  # subscription login shorthand; BYOK `xai` uses keys --set
}

_PROVIDERS: dict[str, AuthProvider] = {
    "chatgpt": CodexAuthProvider(),
    "anthropic": ClaudeCodeAuthProvider(),
    "xai": GrokCliAuthProvider(),
}


def resolve_login_provider(name: str) -> str:
    key = (name or "").strip().lower()
    return LOGIN_ALIASES.get(key, key)


def get_auth_provider(oauth_provider: str) -> AuthProvider | None:
    return _PROVIDERS.get(oauth_provider)


def register_auth_provider(key: str, provider: AuthProvider) -> None:
    _PROVIDERS[key] = provider
