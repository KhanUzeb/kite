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

    def litellm_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.litellm_model}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if is_oauth_provider(self.spec):
            kwargs.update(oauth_litellm_extras(self.spec))
        if self.provider == "ollama":
            kwargs.setdefault("api_key", "ollama")
        return kwargs


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


def resolve_model(
    *,
    provider: str | None = None,
    model: str | None = None,
    config: UserConfig | None = None,
    catalog: Catalog | None = None,
) -> ResolvedModel:
    cfg = config or UserConfig.load()
    cat = catalog or load_catalog()

    requested = provider or cfg.default_provider or "openai"
    spec = cat.get(requested)
    provider_name = spec.name

    model_name = (
        model
        or cfg.provider_defaults.get(provider_name)
        or cfg.provider_defaults.get(requested)
        or cfg.default_model
        or spec.default_model
        or ""
    )

    if not model_name:
        try:
            from kite.providers.list_models import list_models_for_provider

            live = list_models_for_provider(spec, config=cfg, catalog=cat)
            if live.ok:
                model_name = live.models[0].id
        except Exception:  # noqa: BLE001 — resolve must stay non-fatal
            model_name = ""

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
            ensure_oauth_env(spec)
            extras = oauth_litellm_extras(spec)
            if extras.get("api_key"):
                api_key = extras["api_key"]
            elif extras.get("use_xai_oauth"):
                api_key = None
            else:
                api_key = None

    window = cfg.context_window or spec.context_window_for(model_name or "unknown")
    litellm_model = spec.litellm_model_id(model_name) if model_name else ""

    return ResolvedModel(
        provider=provider_name,
        model=model_name,
        litellm_model=litellm_model,
        api_key=api_key,
        api_base=api_base,
        context_window=window,
        spec=spec,
    )


def missing_credentials(resolved: ResolvedModel) -> str | None:
    if resolved.provider == "ollama":
        return None
    if is_oauth_provider(resolved.spec):
        oauth_id = resolved.spec.oauth_provider or resolved.spec.name
        if has_oauth_session(oauth_id):
            return None
        return subscription_login_hint(resolved.spec)
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
