"""Resolve provider + model → LiteLLM call kwargs + context window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kite.config import UserConfig
from kite.providers.byos import (
    ensure_oauth_env,
    has_oauth_session,
    is_oauth_provider,
    oauth_litellm_extras,
    subscription_login_hint,
)
from kite.providers.catalog import Catalog, ProviderSpec, load_catalog
from kite.providers.keys import api_key_env_names, api_key_for


@dataclass(frozen=True)
class ResolvedModel:
    provider: str
    model: str
    litellm_model: str
    api_key: str | None
    api_base: str | None
    context_window: int
    spec: ProviderSpec
    api_style: str = "chat"  # chat | messages | responses
    agent_warning: str | None = None
    raw: dict[str, Any] | None = None  # live catalog payload from resolve (avoids re-fetch)

    def litellm_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.litellm_model}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if is_oauth_provider(self.spec):
            kwargs.update(oauth_litellm_extras(self.spec))
            if (self.spec.oauth_provider or self.spec.name) == "xai" and not self.api_key:
                # Subscription proxy 426s without the CLI version stamp.
                from kite.providers.auth.grok_litellm import xai_subscription_headers

                kwargs["extra_headers"] = xai_subscription_headers()
        if self.provider == "ollama":
            kwargs.setdefault("api_key", "ollama")
        return kwargs


def _default_api_style(provider: str, kind: str) -> str:
  """Provider-native API route — chat completions remain the default for compatibility."""
  if provider == "anthropic" or kind == "anthropic":
      return "messages"
  return "chat"


def _stock_cloud_base(provider: str, api_base: str | None) -> bool:
    if not api_base:
        return False
    markers = {
        "openai": "api.openai.com",
        "groq": "api.groq.com",
        "anthropic": "api.anthropic.com",
        "openrouter": "openrouter.ai",
        "gemini": "generativelanguage.googleapis.com",
        "huggingface": "huggingface.co",
        "nvidia": "integrate.api.nvidia.com",
        "xai": "api.x.ai",
    }
    needle = markers.get(provider)
    return bool(needle and needle in api_base)


def _first_configured_provider() -> str:
    from kite.providers.credentials import configured_providers

    rows = configured_providers()
    usable = [name for name, ok, _env in rows if ok and name != "ollama"]
    if usable:
        return usable[0]
    if any(name == "ollama" and ok for name, ok, _env in rows):
        return "ollama"
    return "openai"


def resolve_model(
    *,
    provider: str | None = None,
    model: str | None = None,
    config: UserConfig | None = None,
    catalog: Catalog | None = None,
) -> ResolvedModel:
    cfg = config or UserConfig.load()
    cat = catalog or load_catalog()

    explicit = bool((provider or "").strip())
    requested = (provider or cfg.default_provider or "").strip()
    rows = None
    if not explicit:
        from kite.providers.credentials import configured_providers

        rows = configured_providers()
        ready = {name for name, ok, _env in rows if ok}
        if not requested or requested not in ready:
            usable = [name for name, ok, _env in rows if ok and name != "ollama"]
            if usable:
                requested = usable[0]
            elif any(name == "ollama" and ok for name, ok, _env in rows):
                requested = "ollama"
            elif not requested:
                requested = "openai"
    if not requested:
        requested = _first_configured_provider()
    spec = cat.get(requested)
    provider_name = spec.name

    saved_default = ""
    if cfg.default_model and (cfg.default_provider or "") in {provider_name, requested}:
        saved_default = cfg.default_model
    model_name = (
        model
        or cfg.provider_defaults.get(provider_name)
        or cfg.provider_defaults.get(requested)
        or saved_default
        or spec.default_model
        or ""
    )

    api_base = (
        cfg.api_bases.get(provider_name)
        or cfg.api_bases.get(requested)
        or (spec.base_url or None)
    )
    if provider_name == "openai-compatible":
        api_base = cfg.api_bases.get(provider_name) or (spec.base_url or None)
    elif _stock_cloud_base(provider_name, api_base):
        api_base = None

    api_key = api_key_for(spec)
    if is_oauth_provider(spec):
        oauth_id = spec.oauth_provider or spec.name
        if not has_oauth_session(oauth_id):
            api_key = None
        else:
            try:
                ensure_oauth_env(spec)
            except Exception as exc:  # noqa: BLE001 — resolve must stay non-fatal
                import logging

                logging.getLogger("kite.providers.resolve").debug(
                    "oauth env prepare failed for %s: %s", provider_name, exc
                )
            extras = oauth_litellm_extras(spec)
            if extras.get("api_key"):
                api_key = extras["api_key"]
            elif extras.get("use_xai_oauth"):
                api_key = None
            else:
                api_key = None
            if spec.oauth_provider in {"anthropic", "antigravity"}:
                # Claude/Antigravity subscription auth is CLI-owned; LiteLLM
                # needs a BYOK API key for direct calls.
                api_key = api_key_for(spec) or None

    window = cfg.context_window or spec.context_window_for(model_name or "unknown")
    litellm_model = spec.litellm_model_id(model_name) if model_name else ""

    api_style = (
        cfg.api_styles.get(provider_name)
        or cfg.api_styles.get(requested)
        or _default_api_style(provider_name, spec.kind)
    )

    from kite.providers.capabilities import agent_model_warning

    # Name-only warning — do not fetch live catalogs or import LiteLLM here.
    # Those belong in the model picker / first model call, not every `kite` launch.
    warning = agent_model_warning(model_name or "", local_only=True)
    remote_raw: dict[str, Any] | None = None

    return ResolvedModel(
        provider=provider_name,
        model=model_name,
        litellm_model=litellm_model,
        api_key=api_key,
        api_base=api_base,
        context_window=window,
        spec=spec,
        api_style=api_style,
        agent_warning=warning,
        raw=remote_raw,
    )


def missing_credentials(resolved: ResolvedModel) -> str | None:
    if resolved.provider == "ollama":
        return None
    if is_oauth_provider(resolved.spec):
        oauth_id = resolved.spec.oauth_provider or resolved.spec.name
        if not has_oauth_session(oauth_id):
            return subscription_login_hint(resolved.spec)
        if resolved.spec.oauth_provider == "anthropic" and not resolved.api_key:
            return (
                "Claude Code is linked, but Kite model calls need ANTHROPIC_API_KEY. "
                "Run `kite keys --set anthropic`."
            )
        if resolved.spec.oauth_provider == "antigravity" and not resolved.api_key:
            return (
                "Antigravity is linked, but Kite model calls need GEMINI_API_KEY. "
                "Run `kite keys --set gemini`."
            )
        if oauth_id == "chatgpt":
            try:
                from kite.providers.auth.codex_litellm import materialize_litellm_chatgpt_auth

                materialize_litellm_chatgpt_auth()
            except Exception as exc:  # noqa: BLE001 — surface bridge errors to the user
                return str(exc)
        if oauth_id == "xai":
            try:
                from kite.providers.auth.grok_litellm import materialize_litellm_xai_auth

                materialize_litellm_xai_auth()
            except Exception as exc:  # noqa: BLE001 — surface bridge errors to the user
                return str(exc)
        return None
    if resolved.spec.api_key_env and not resolved.api_key:
        names = " or ".join(f"${n}" for n in api_key_env_names(resolved.spec))
        return (
            f"Missing {names} for provider '{resolved.provider}'. "
            f"See {resolved.spec.docs_url or 'provider docs'}."
        )
    return None


def missing_model(resolved: ResolvedModel) -> str | None:
    if resolved.model:
        return None
    return (
        f"No model selected for provider '{resolved.provider}'. "
        f"Run: kite models -p {resolved.provider} --select"
    )
