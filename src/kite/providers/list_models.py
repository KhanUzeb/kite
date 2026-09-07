"""Fetch available models from a provider using the configured API key."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from kite.config import UserConfig
from kite.providers.catalog import Catalog, ProviderSpec, load_catalog
from kite.providers.keys import api_key_env_names, api_key_for

_LIST_CACHE: dict[str, tuple[float, ListModelsResult]] = {}
_LIST_TTL = 90.0


def clear_model_list_cache(provider: str | None = None) -> None:
    """Drop cached live model lists (and matching OAuth model cache)."""
    if provider:
        _LIST_CACHE.pop(provider, None)
        try:
            from kite.providers.byos import clear_oauth_model_cache

            clear_oauth_model_cache(provider)
        except Exception:
            pass
        return
    _LIST_CACHE.clear()
    try:
        from kite.providers.byos import clear_oauth_model_cache

        clear_oauth_model_cache()
    except Exception:
        pass

# Modality ids that are useless for the coding agent (not a hard model allowlist).
_NON_CHAT_HINTS = (
    "rerank",
    "whisper",
    "tts",
    "embed",
    "embedding",
    "dall-e",
    "dalle",
    "moderation",
    "realtime",
    "audio",
    "transcribe",
    "speak",
    "image",
)


@dataclass(frozen=True)
class RemoteModel:
    id: str
    context_window: int | None = None
    owned_by: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def is_free(self) -> bool:
        """True when the live payload marks this model as free (suffix or zero price)."""
        low = self.id.lower()
        if low.endswith(":free") or low.endswith("/free"):
            return True
        pricing = self.raw.get("pricing")
        if not isinstance(pricing, dict):
            return False
        try:
            prompt = float(pricing.get("prompt") if pricing.get("prompt") is not None else 1)
            completion = float(pricing.get("completion") if pricing.get("completion") is not None else 1)
        except (TypeError, ValueError):
            return False
        return prompt == 0.0 and completion == 0.0

    def parameter_names(self) -> frozenset[str]:
        return frozenset(_collect_parameter_names(self.raw))

    def input_modalities(self) -> frozenset[str]:
        return frozenset(_collect_input_modalities(self.raw))

    def supports_vision(self) -> bool:
        mods = {m.lower() for m in self.input_modalities()}
        if mods & {"image", "images", "vision", "visual"}:
            return True
        params = self.parameter_names()
        if params & {"vision", "image", "images", "image_url"}:
            return True
        details = self.raw.get("details") if isinstance(self.raw.get("details"), dict) else {}
        families = details.get("families") if isinstance(details, dict) else None
        if isinstance(families, (list, tuple)):
            for item in families:
                low = str(item).lower()
                if "clip" in low or "vision" in low:
                    return True
        return False


@dataclass(frozen=True)
class ListModelsResult:
    provider: str
    models: tuple[RemoteModel, ...]
    source: str  # "live"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.models)


def _api_key(spec: ProviderSpec) -> str | None:
    return api_key_for(spec)


def _http_json(url: str, headers: dict[str, str], *, timeout: float = 30.0) -> Any:
    # Cloudflare (and some WAFs) reject urllib's default "Python-urllib/…" UA (error 1010).
    merged = {
        "User-Agent": "kite/0.4.0 (https://github.com/local/kite; +OpenAI-compatible client)",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    merged.update(headers)
    req = urllib.request.Request(url, headers=merged, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_chatish(model_id: str) -> bool:
    low = model_id.lower()
    return not any(h in low for h in _NON_CHAT_HINTS)


def _openai_compat_base(spec: ProviderSpec, cfg: UserConfig) -> str:
    override = cfg.api_bases.get(spec.name)
    if override:
        return override.rstrip("/")
    if spec.base_url:
        return spec.base_url.rstrip("/")
    # Built-in defaults when catalog leaves base_url empty (e.g. litellm-native groq).
    defaults = {
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "huggingface": "https://router.huggingface.co/v1",
        "ollama": "http://localhost:11434/v1",
        "openai-compatible": "http://localhost:8000/v1",
        "opencode-zen": "https://opencode.ai/zen/v1",
        "opencode-go": "https://opencode.ai/zen/go/v1",
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "xai": "https://api.x.ai/v1",
    }
    return defaults.get(spec.name, "").rstrip("/")


def _parse_openai_style(data: Any) -> list[RemoteModel]:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[RemoteModel] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "").strip()
        if not mid:
            continue
        if row.get("active") is False:
            continue
        ctx = row.get("context_window") or row.get("context_length") or row.get("max_model_len")
        try:
            context = int(ctx) if ctx is not None else None
        except (TypeError, ValueError):
            context = None
        owned = row.get("owned_by") or row.get("ownedBy")
        out.append(
            RemoteModel(
                id=mid,
                context_window=context,
                owned_by=str(owned) if owned else None,
                raw=row,
            )
        )
    return out


def _fetch_openai_compatible(spec: ProviderSpec, cfg: UserConfig) -> ListModelsResult:
    base = _openai_compat_base(spec, cfg)
    if not base:
        return ListModelsResult(spec.name, (), "live", error=f"No models API base URL for '{spec.name}'")
    key = _api_key(spec)
    if spec.api_key_env and not key:
        names = " or ".join(f"${n}" for n in api_key_env_names(spec))
        return ListModelsResult(
            spec.name,
            (),
            "live",
            error=f"Missing {names} — set it to list live models",
        )
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = f"{base}/models"
    try:
        data = _http_json(url, headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return ListModelsResult(spec.name, (), "live", error=f"HTTP {e.code} from {url}: {body}")
    except Exception as e:  # noqa: BLE001 — surface network errors to CLI
        return ListModelsResult(spec.name, (), "live", error=f"{type(e).__name__}: {e}")
    models = [m for m in _parse_openai_style(data) if _is_chatish(m.id)]
    models.sort(key=lambda m: m.id.lower())
    if not models:
        return ListModelsResult(spec.name, (), "live", error=f"No chat models returned from {url}")
    return ListModelsResult(spec.name, tuple(models), "live")


def _fetch_anthropic(spec: ProviderSpec, cfg: UserConfig) -> ListModelsResult:
    key = _api_key(spec)
    if not key:
        return ListModelsResult(
            spec.name,
            (),
            "live",
            error=f"Missing ${spec.api_key_env} — set it to list live models",
        )
    base = (cfg.api_bases.get(spec.name) or spec.base_url or "https://api.anthropic.com").rstrip("/")
    url = f"{base}/v1/models"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    try:
        data = _http_json(url, headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return ListModelsResult(spec.name, (), "live", error=f"HTTP {e.code} from {url}: {body}")
    except Exception as e:  # noqa: BLE001
        return ListModelsResult(spec.name, (), "live", error=f"{type(e).__name__}: {e}")
    models = [m for m in _parse_openai_style(data) if _is_chatish(m.id)]
    models.sort(key=lambda m: m.id.lower())
    if not models:
        return ListModelsResult(spec.name, (), "live", error=f"No models returned from {url}")
    return ListModelsResult(spec.name, tuple(models), "live")


def _redact_url_secrets(url: str) -> str:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    if not parsed.query:
        return url
    qs = parse_qs(parsed.query, keep_blank_values=True)
    for secret_key in ("key", "api_key", "token", "access_token"):
        if secret_key in qs:
            qs[secret_key] = ["[REDACTED]"]
    redacted_query = urlencode({k: v[0] if len(v) == 1 else v for k, v in qs.items()}, doseq=True)
    return urlunparse(parsed._replace(query=redacted_query))


def _fetch_gemini(spec: ProviderSpec, cfg: UserConfig) -> ListModelsResult:
    key = _api_key(spec)
    if not key:
        return ListModelsResult(
            spec.name,
            (),
            "live",
            error=f"Missing ${spec.api_key_env} — set it to list live models",
        )
    base = (
        cfg.api_bases.get(spec.name)
        or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    url = f"{base}/models?key={urllib.parse.quote(key)}"
    try:
        data = _http_json(url, {"Accept": "application/json"})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        body = body.replace(key, "[REDACTED]")
        return ListModelsResult(spec.name, (), "live", error=f"HTTP {e.code}: {body}")
    except Exception as e:  # noqa: BLE001
        msg = str(e).replace(key, "[REDACTED]")
        return ListModelsResult(spec.name, (), "live", error=f"{type(e).__name__}: {msg}")

    rows = data.get("models") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return ListModelsResult(spec.name, (), "live", error="Unexpected Gemini models response")
    out: list[RemoteModel] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").removeprefix("models/").strip()
        methods = row.get("supportedGenerationMethods") or []
        if methods and "generateContent" not in methods:
            continue
        if not name or not _is_chatish(name):
            continue
        ctx = row.get("inputTokenLimit")
        try:
            context = int(ctx) if ctx is not None else None
        except (TypeError, ValueError):
            context = None
        out.append(RemoteModel(id=name, context_window=context, owned_by="google", raw=row))
    out.sort(key=lambda m: m.id.lower())
    if not out:
        return ListModelsResult(spec.name, (), "live", error="No Gemini generateContent models found")
    return ListModelsResult(spec.name, tuple(out), "live")


def _fetch_ollama(spec: ProviderSpec, cfg: UserConfig) -> ListModelsResult:
    base = (cfg.api_bases.get(spec.name) or spec.base_url or "http://localhost:11434").rstrip("/")
    # Prefer native tags API (always present); fall back to OpenAI-compat /v1/models.
    tags_url = f"{base.removesuffix('/v1')}/api/tags"
    try:
        data = _http_json(tags_url, {"Accept": "application/json"})
        rows = data.get("models") if isinstance(data, dict) else None
        if isinstance(rows, list):
            out: list[RemoteModel] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mid = str(row.get("name") or row.get("model") or "").strip()
                if not mid:
                    continue
                out.append(RemoteModel(id=mid, owned_by="ollama", raw=row))
            out.sort(key=lambda m: m.id.lower())
            if out:
                return ListModelsResult(spec.name, tuple(out), "live")
    except Exception:
        pass
    return _fetch_openai_compatible(spec, cfg)


def _collect_parameter_names(raw: dict[str, Any]) -> set[str]:
    """Pull capability / parameter names out of a live model payload."""
    found: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            found.add(value.strip().lower().replace("-", "_"))
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                add(value=item)

    for key in (
        "supported_parameters",
        "supported_params",
        "supportedParameters",
        "supportedGenerationMethods",
        "supported_generation_methods",
    ):
        val = raw.get(key)
        if isinstance(val, dict):
            add(list(val.keys()))
        else:
            add(val)

    for key in ("capabilities", "features", "supports"):
        val = raw.get(key)
        if isinstance(val, dict):
            for name, flag in val.items():
                if flag:
                    add(name)
        else:
            add(val)

    reasoning = raw.get("reasoning")
    if isinstance(reasoning, dict):
        found.add("reasoning")
        add(reasoning.get("supported_parameters"))
        add(reasoning.get("supported_efforts"))
        if reasoning.get("supported") or reasoning.get("enabled") or reasoning.get("supported_efforts"):
            found.add("reasoning")

    return found


def _collect_input_modalities(raw: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str):
            text = value.strip().lower()
            if not text:
                return
            # OpenRouter: "text+image->text"
            if "->" in text:
                text = text.split("->", 1)[0]
            for piece in re.split(r"[+,\s/|]+", text):
                if piece:
                    found.add(piece.replace("-", "_"))
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                add(item)
        elif isinstance(value, dict):
            for key, flag in value.items():
                if flag:
                    add(key)

    arch = raw.get("architecture")
    if isinstance(arch, dict):
        add(arch.get("input_modalities") or arch.get("input_modality") or arch.get("modality"))
    for key in ("input_modalities", "inputModalities", "modalities"):
        add(raw.get(key))
    caps = raw.get("capabilities") or raw.get("supports")
    if isinstance(caps, dict):
        for name in ("vision", "image", "images", "multimodal"):
            if caps.get(name):
                found.add(name)
    return found


def _ids_equal(listed: str, wanted: str) -> bool:
    a = listed.lower().strip()
    b = wanted.lower().strip().removeprefix("openrouter/")
    if a == b:
        return True
    if a.endswith("/" + b) or b.endswith("/" + a):
        return True
    return a.split("/")[-1] == b.split("/")[-1] and bool(a.split("/")[-1])


def find_remote_model(
    provider: str | ProviderSpec,
    model: str,
    *,
    config: UserConfig | None = None,
    catalog: Catalog | None = None,
) -> RemoteModel | None:
    """Resolve a model id against the live provider catalog."""
    wanted = (model or "").strip()
    if not wanted:
        return None
    result = list_models_for_provider(provider, config=config, catalog=catalog)
    if not result.ok:
        return None
    exact = [m for m in result.models if _ids_equal(m.id, wanted)]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return exact[0]
    needle = wanted.lower().removeprefix("openrouter/")
    hits = [m for m in result.models if needle in m.id.lower() or m.id.lower() in needle]
    return hits[0] if len(hits) == 1 else None


def list_free_models(
    provider: str | ProviderSpec = "openrouter",
    *,
    config: UserConfig | None = None,
    catalog: Catalog | None = None,
) -> ListModelsResult:
    """Live models whose payload says they are free (OpenRouter :free / zero price)."""
    result = list_models_for_provider(provider, config=config, catalog=catalog)
    if result.error:
        return result
    free = tuple(m for m in result.models if m.is_free())
    if not free:
        return ListModelsResult(result.provider, (), result.source, error="No free-tier models in live catalog")
    return ListModelsResult(result.provider, free, result.source)


def list_models_for_provider(
    provider: str | ProviderSpec,
    *,
    config: UserConfig | None = None,
    catalog: Catalog | None = None,
    refresh: bool = False,
) -> ListModelsResult:
    """Fetch live models for one provider using its API key / local endpoint."""
    cfg = config or UserConfig.load()
    cat = catalog or load_catalog()
    spec = provider if isinstance(provider, ProviderSpec) else cat.get(provider)

    from kite.providers.byos import fetch_oauth_model_ids, has_oauth_session, is_oauth_provider

    if is_oauth_provider(spec):
        ids = fetch_oauth_model_ids(spec, refresh=refresh)
        models = tuple(RemoteModel(id=m) for m in ids)
        source = "oauth" if has_oauth_session(spec.oauth_provider or spec.name) else "catalog-fallback"
        if not models:
            return ListModelsResult(spec.name, (), source, error="No models — run: kite login " + spec.name)
        return ListModelsResult(spec.name, models, source)

    cache_key = spec.name
    now = time.monotonic()
    if not refresh:
        hit = _LIST_CACHE.get(cache_key)
        if hit and now - hit[0] < _LIST_TTL:
            return hit[1]

    kind = (spec.kind or "").lower()
    name = spec.name

    if name == "anthropic" or kind == "anthropic":
        result = _fetch_anthropic(spec, cfg)
    elif name == "gemini" or kind == "gemini":
        result = _fetch_gemini(spec, cfg)
    elif name == "ollama":
        result = _fetch_ollama(spec, cfg)
    elif name == "xai" or kind == "xai":
        result = _fetch_openai_compatible(spec, cfg)
    else:
        # openai, groq, openrouter, huggingface, openai-compatible, …
        result = _fetch_openai_compatible(spec, cfg)

    if result.ok:
        _LIST_CACHE[cache_key] = (now, result)
    return result


def list_models(
    provider: str | None = None,
    *,
    config: UserConfig | None = None,
    catalog: Catalog | None = None,
) -> list[ListModelsResult]:
    cfg = config or UserConfig.load()
    cat = catalog or load_catalog()
    names = [provider] if provider else [p.name for p in cat.list()]
    return [list_models_for_provider(n, config=cfg, catalog=cat) for n in names]
