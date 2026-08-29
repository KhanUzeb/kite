"""Config-driven provider catalog (tau-style, slim)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from kite.config import kite_home


# Short names accepted by `kite models -p` / `-p`.
ALIASES: dict[str, str] = {
    "zen": "opencode-zen",
    "opencode": "opencode-zen",
    "go": "opencode-go",
    "nim": "nvidia",
    "nvidia-nim": "nvidia",
    "nvidia_nim": "nvidia",
}


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    display_name: str
    kind: str
    litellm_prefix: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...]
    default_model: str
    docs_url: str = ""
    context_windows: dict[str, int] = field(default_factory=dict)

    def litellm_model_id(self, model: str) -> str:
        """Map catalog model id → LiteLLM model string."""
        if self.name == "openai":
            return model
        if self.name == "openrouter":
            return model if model.startswith("openrouter/") else f"openrouter/{model}"
        # Named LiteLLM routes keep their prefix. Other OpenAI-compatible
        # gateways (OpenCode Zen/Go, custom) use openai/ + api_base.
        native = {"huggingface", "ollama", "groq", "nvidia"}
        if self.name == "openai-compatible" or (
            self.kind == "openai-compatible" and self.name not in native
        ):
            bare = model.removeprefix("openai/")
            return f"openai/{bare}"
        prefix = self.litellm_prefix
        if prefix and not model.startswith(prefix):
            return f"{prefix}{model}"
        return model

    def context_window_for(self, model: str, fallback: int = 128_000) -> int:
        if model in self.context_windows:
            return self.context_windows[model]
        # strip prefix variants
        bare = model.split("/", 1)[-1]
        for key, value in self.context_windows.items():
            if key == bare or key.endswith(model) or model.endswith(key):
                return value
        return fallback


@dataclass
class Catalog:
    providers: dict[str, ProviderSpec]

    def get(self, name: str) -> ProviderSpec:
        key = ALIASES.get(name, name)
        if key not in self.providers:
            known = ", ".join(sorted(self.providers))
            raise KeyError(f"Unknown provider '{name}'. Known: {known}")
        return self.providers[key]

    def list(self) -> list[ProviderSpec]:
        return list(self.providers.values())


def _parse_providers(data: dict[str, Any]) -> dict[str, ProviderSpec]:
    out: dict[str, ProviderSpec] = {}
    for raw in data.get("providers") or []:
        name = str(raw["name"])
        ctx = dict(raw.get("context_windows") or {})
        # TOML may nest context_windows oddly depending on structure; handle both
        out[name] = ProviderSpec(
            name=name,
            display_name=str(raw.get("display_name") or name),
            kind=str(raw.get("kind") or "openai-compatible"),
            litellm_prefix=str(raw.get("litellm_prefix") or ""),
            base_url=str(raw.get("base_url") or ""),
            api_key_env=str(raw.get("api_key_env") or ""),
            models=tuple(str(m) for m in (raw.get("models") or [])),
            default_model=str(raw.get("default_model") or ""),
            docs_url=str(raw.get("docs_url") or ""),
            context_windows={str(k): int(v) for k, v in ctx.items()},
        )
    return out


def _load_toml_bytes(raw: bytes) -> dict[str, Any]:
    return tomllib.loads(raw.decode("utf-8"))


def _merge_provider(base: ProviderSpec, overlay: ProviderSpec) -> ProviderSpec:
    models = tuple(dict.fromkeys([*overlay.models, *base.models]))
    windows = {**base.context_windows, **overlay.context_windows}
    return ProviderSpec(
        name=base.name,
        display_name=overlay.display_name or base.display_name,
        kind=overlay.kind or base.kind,
        litellm_prefix=overlay.litellm_prefix if overlay.litellm_prefix != "" else base.litellm_prefix,
        base_url=overlay.base_url or base.base_url,
        api_key_env=overlay.api_key_env if overlay.api_key_env != "" else base.api_key_env,
        models=models or base.models,
        default_model=overlay.default_model or base.default_model,
        docs_url=overlay.docs_url or base.docs_url,
        context_windows=windows,
    )


def load_catalog() -> Catalog:
    """Load packaged catalog, then overlay ~/.kite/catalog.toml."""
    pkg = resources.files("kite").joinpath("data/catalog.toml")
    data = _load_toml_bytes(pkg.read_bytes())
    providers = _parse_providers(data)

    user_path = kite_home() / "catalog.toml"
    if user_path.is_file():
        user = _parse_providers(_load_toml_bytes(user_path.read_bytes()))
        for name, spec in user.items():
            if name in providers:
                providers[name] = _merge_provider(providers[name], spec)
            else:
                providers[name] = spec

    return Catalog(providers=providers)


def load_builtin_catalog_path() -> Path:
    return Path(str(resources.files("kite").joinpath("data/catalog.toml")))
