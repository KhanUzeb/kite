"""Detect vision / multimodal from live provider payloads + LiteLLM.

No model-id allowlist. If the catalog says the model accepts image input,
or LiteLLM `supports_vision` does, we treat it as multimodal.
"""

from __future__ import annotations

from dataclasses import dataclass

from kite.config import UserConfig
from kite.providers.catalog import load_catalog
from kite.providers.keys import api_key_for
from kite.providers.list_models import RemoteModel, find_remote_model, list_models_for_provider
from kite.providers.resolve import ResolvedModel, resolve_model


@dataclass(frozen=True)
class VisionRoute:
    provider: str
    model: str
    source: str  # current | same-provider | other-provider | none
    switched: bool


def _litellm_vision(litellm_model: str) -> bool:
    if not litellm_model:
        return False
    try:
        import litellm

        return bool(litellm.supports_vision(model=litellm_model))
    except Exception:
        return False


def model_supports_vision(
    provider: str,
    model: str,
    *,
    config: UserConfig | None = None,
    remote: RemoteModel | None = None,
    litellm_model: str = "",
) -> bool:
    row = remote or find_remote_model(provider, model, config=config)
    if row is not None and row.supports_vision():
        return True
    if litellm_model and _litellm_vision(litellm_model):
        return True
    if not litellm_model:
        try:
            resolved = resolve_model(provider=provider, model=model, config=config)
            return _litellm_vision(resolved.litellm_model)
        except Exception:
            return False
    return False


def _providers_to_try(preferred: str, config: UserConfig) -> list[str]:
    catalog = load_catalog()
    names = [preferred] if preferred else []
    for spec in catalog.list():
        if spec.name in names:
            continue
        if spec.name == "ollama" or api_key_for(spec):
            names.append(spec.name)
    return names


def _pick_vision(provider: str, *, config: UserConfig | None, prefer: str = "") -> RemoteModel | None:
    result = list_models_for_provider(provider, config=config)
    if not result.ok:
        return None
    if prefer:
        for row in result.models:
            if row.id == prefer and row.supports_vision():
                return row
    vision = [m for m in result.models if m.supports_vision()]
    if not vision:
        return None
    vision.sort(key=lambda m: (0 if m.is_free() else 1, -(m.context_window or 0), m.id.lower()))
    return vision[0]


def route_vision(
    resolved: ResolvedModel,
    *,
    config: UserConfig | None = None,
) -> VisionRoute:
    """Stay on the current model if it can see; else pick a live vision model."""
    cfg = config or UserConfig.load()
    if model_supports_vision(
        resolved.provider,
        resolved.model,
        config=cfg,
        litellm_model=resolved.litellm_model,
    ):
        return VisionRoute(resolved.provider, resolved.model, "current", False)

    same = _pick_vision(resolved.provider, config=cfg, prefer=resolved.model)
    if same is not None:
        return VisionRoute(resolved.provider, same.id, "same-provider", True)

    for name in _providers_to_try(resolved.provider, cfg)[1:]:
        hit = _pick_vision(name, config=cfg)
        if hit is not None:
            return VisionRoute(name, hit.id, "other-provider", True)

    return VisionRoute(resolved.provider, resolved.model, "none", False)
