"""Detect and apply thinking / fast from live provider + LiteLLM metadata.

No model-id allowlist. Support is whatever the current API payload and
LiteLLM supported params say for this provider+model.

LiteLLM `supports_reasoning` is not treated as license to send
`extra_body.include_reasoning` — that field is OpenRouter-style and NVIDIA NIM
rejects it as an unsupported parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ReasoningMode = Literal["auto", "off", "fast", "thinking"]

MODES: tuple[ReasoningMode, ...] = ("auto", "off", "fast", "thinking")

_REASONING_PARAMS = frozenset(
    {
        "reasoning",
        "include_reasoning",
        "reasoning_effort",
        "thinking",
        "thinking_config",
        "thinkingconfig",
        "reasoning_max_tokens",
        "max_reasoning_tokens",
    }
)

# Effort order as advertised by OpenRouter / OpenAI-style APIs.
_EFFORT_RANK = ("none", "disable", "disabled", "minimal", "min", "low", "medium", "high", "xhigh", "max")

_cache: dict[tuple[str, str], "ReasoningSupport"] = {}


# extra_body.include_reasoning is OpenRouter-style. Strict OpenAI clones
# (NVIDIA NIM, Groq, Ollama) validate the body and reject the field.
_NO_INCLUDE_REASONING = frozenset({"nvidia", "nvidia_nim", "groq", "ollama"})
_INCLUDE_REASONING_PROVIDERS = frozenset({"openrouter"})
_REASONING_BODY_KEYS = frozenset({"include_reasoning", "reasoning", "thinking", "thinking_config"})


@dataclass(frozen=True)
class ReasoningSupport:
    supported: bool
    can_fast: bool
    can_thinking: bool
    can_disable: bool
    thinking_kwargs: dict[str, Any] = field(default_factory=dict)
    fast_kwargs: dict[str, Any] = field(default_factory=dict)
    off_kwargs: dict[str, Any] = field(default_factory=dict)
    source: str = "none"  # live | litellm | none
    efforts: tuple[str, ...] = ()
    include_reasoning: bool = False

    @property
    def label(self) -> str:
        if not self.supported:
            return ""
        bits = []
        if self.can_thinking:
            bits.append("thinking")
        if self.can_fast:
            bits.append("fast")
        return "/".join(bits) or "reasoning"


def parse_mode(raw: str | None) -> ReasoningMode:
    text = (raw or "auto").strip().lower()
    aliases = {
        "think": "thinking",
        "reason": "thinking",
        "high": "thinking",
        "low": "fast",
        "minimal": "fast",
        "min": "fast",
        "none": "off",
        "disable": "off",
        "disabled": "off",
    }
    text = aliases.get(text, text)
    if text in MODES:
        return text  # type: ignore[return-value]
    return "auto"


def _norm_params(values: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(values, dict):
        values = list(values.keys())
    if not isinstance(values, (list, tuple, set, frozenset)):
        return out
    for item in values:
        if isinstance(item, str) and item.strip():
            out.add(item.strip().lower().replace("-", "_"))
    return out


def _effort_rank(name: str) -> int:
    low = name.lower()
    try:
        return _EFFORT_RANK.index(low)
    except ValueError:
        return len(_EFFORT_RANK) // 2


def _pick_efforts(supported: list[str]) -> tuple[str | None, str | None]:
    """thinking = highest advertised effort, fast = lowest (excluding off)."""
    usable = [e for e in supported if e.lower() not in {"none", "disable", "disabled"}]
    if not usable:
        return None, None
    ordered = sorted(usable, key=_effort_rank)
    return ordered[-1], ordered[0]


def _params_from_remote(raw: dict[str, Any]) -> tuple[set[str], list[str], bool]:
    from kite.providers.list_models import RemoteModel

    dummy = RemoteModel(id="", raw=raw)
    params = set(dummy.parameter_names())
    efforts: list[str] = []
    mandatory = False
    blob = raw.get("reasoning")
    if isinstance(blob, dict):
        params.add("reasoning")
        raw_efforts = blob.get("supported_efforts") or blob.get("efforts") or []
        if isinstance(raw_efforts, list):
            efforts = [str(e) for e in raw_efforts if e]
        mandatory = bool(blob.get("mandatory"))
    return params, efforts, mandatory


def _params_from_litellm(provider: str, model: str, litellm_model: str) -> set[str]:
    """Collect reasoning *request* params LiteLLM lists for this model.

    `supports_reasoning` only means the model can emit thinking tokens. It
    does not mean the HTTP API accepts `extra_body.reasoning` or
    `include_reasoning` — NVIDIA NIM rejects both even when LiteLLM says
    the model supports reasoning.
    """
    found: set[str] = set()
    try:
        import litellm
    except Exception:
        return found
    mid = litellm_model or model
    try:
        extra: dict[str, Any] = {}
        if provider:
            extra["custom_llm_provider"] = provider
        params = litellm.get_supported_openai_params(model=mid, **extra)
        found |= _norm_params(params) & (_REASONING_PARAMS | {"reasoning_effort", "thinking"})
    except Exception:
        try:
            params = litellm.get_supported_openai_params(model=mid)
            found |= _norm_params(params) & (_REASONING_PARAMS | {"reasoning_effort", "thinking"})
        except Exception:
            pass
    return found


def _kwargs_from_params(
    params: set[str],
    *,
    efforts: list[str],
    mandatory: bool,
    provider: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool, bool, bool]:
    params = {p.lower().replace("-", "_") for p in params}
    thinking: dict[str, Any] = {}
    fast: dict[str, Any] = {}
    off: dict[str, Any] = {}
    can_t = can_f = can_off = False

    high, low = _pick_efforts(efforts) if efforts else ("high", "low")

    if "reasoning_effort" in params:
        thinking["reasoning_effort"] = high or "high"
        fast["reasoning_effort"] = low or "low"
        if not mandatory:
            off["reasoning_effort"] = "none"
        can_t = can_f = True
        can_off = not mandatory

    if "reasoning" in params:
        can_t = can_f = True
        can_off = can_off or (not mandatory)
        # extra_body.reasoning is OpenRouter-style; NIM/Groq/Ollama reject it.
        if provider not in _NO_INCLUDE_REASONING:
            extra_t = dict(thinking.get("extra_body") or {})
            extra_f = dict(fast.get("extra_body") or {})
            extra_o = dict(off.get("extra_body") or {})
            extra_t["reasoning"] = {"effort": high or "high"}
            extra_f["reasoning"] = {"effort": low or "low", "exclude": True}
            thinking["extra_body"] = extra_t
            fast["extra_body"] = extra_f
            if not mandatory:
                extra_o["reasoning"] = {"enabled": False}
                off["extra_body"] = extra_o
            if provider == "openrouter":
                thinking.setdefault("reasoning_effort", high or "high")
                fast.setdefault("reasoning_effort", low or "low")

    if "thinking" in params or "thinking_config" in params or "thinkingconfig" in params:
        thinking["thinking"] = {"type": "enabled"}
        fast["thinking"] = {"type": "disabled"}
        if not mandatory:
            off["thinking"] = {"type": "disabled"}
        can_t = True
        can_f = True
        can_off = can_off or (not mandatory)

    if "include_reasoning" in params:
        for blob in (thinking, fast):
            extra = dict(blob.get("extra_body") or {})
            extra["include_reasoning"] = True
            blob["extra_body"] = extra

    return thinking, fast, off, can_t, can_f, can_off


def _wants_include_reasoning(provider: str, params: set[str], *, can_reason: bool) -> bool:
    provider = (provider or "").strip().lower()
    if provider in _NO_INCLUDE_REASONING:
        return False
    if "include_reasoning" in params:
        return True
    return bool(can_reason and provider in _INCLUDE_REASONING_PROVIDERS)


def detect_reasoning(
    provider: str,
    model: str,
    *,
    supported_parameters: list[str] | None = None,
    config: Any = None,
    remote: Any = None,
    litellm_model: str = "",
    refresh: bool = False,
) -> ReasoningSupport:
    """Ask the live models API + LiteLLM whether thinking/fast exist for this pair."""
    provider = (provider or "").strip().lower()
    model = (model or "").strip()
    key = (provider, model)
    if not refresh and key in _cache and remote is None and supported_parameters is None:
        return _cache[key]

    params: set[str] = _norm_params(supported_parameters)
    efforts: list[str] = []
    mandatory = False
    sources: list[str] = []

    if remote is None and provider and model:
        try:
            from kite.providers.list_models import find_remote_model

            remote = find_remote_model(provider, model, config=config)
        except Exception:
            remote = None

    if remote is not None:
        raw = getattr(remote, "raw", None) or {}
        if isinstance(raw, dict):
            rp, efforts, mandatory = _params_from_remote(raw)
            params |= rp
            if rp:
                sources.append("live")

    llm_id = litellm_model
    if not llm_id:
        try:
            from kite.providers.resolve import resolve_model

            resolved = resolve_model(provider=provider or None, model=model or None, config=config)
            llm_id = resolved.litellm_model
            provider = provider or resolved.provider
        except Exception:
            llm_id = model

    llm_params = _params_from_litellm(provider, model, llm_id)
    if llm_params:
        params |= llm_params
        sources.append("litellm")

    if provider in _NO_INCLUDE_REASONING:
        params.discard("include_reasoning")

    if not (params & _REASONING_PARAMS) and "reasoning" not in params:
        support = ReasoningSupport(False, False, False, False, source="none")
        _cache[key] = support
        return support

    thinking, fast, off, can_t, can_f, can_off = _kwargs_from_params(
        params, efforts=efforts, mandatory=mandatory, provider=provider
    )
    if not (can_t or can_f):
        support = ReasoningSupport(False, False, False, False, source="none")
        _cache[key] = support
        return support

    support = ReasoningSupport(
        supported=True,
        can_fast=can_f,
        can_thinking=can_t,
        can_disable=can_off,
        thinking_kwargs=thinking,
        fast_kwargs=fast,
        off_kwargs=off,
        source="+".join(sources) or "live",
        efforts=tuple(efforts),
        include_reasoning=_wants_include_reasoning(provider, params, can_reason=True),
    )
    _cache[key] = support
    return support


def apply_reasoning(
    kwargs: dict[str, Any],
    support: ReasoningSupport,
    mode: ReasoningMode,
    *,
    drop_reasoning: bool = False,
) -> dict[str, Any]:
    """Merge thinking/fast params into LiteLLM completion kwargs. `auto` sends nothing.

    `include_reasoning` is only added when the provider actually accepts it.
    LiteLLM merges extra_body into the JSON body, so unknown fields (NVIDIA NIM)
    become 400s rather than being dropped.
    """
    out = dict(kwargs)
    extra: dict[str, Any] = {}
    if not drop_reasoning and mode != "auto" and support.supported:
        if mode == "thinking" and support.can_thinking:
            extra = dict(support.thinking_kwargs)
        elif mode == "fast" and support.can_fast:
            extra = dict(support.fast_kwargs)
        elif mode == "off" and support.can_disable:
            extra = dict(support.off_kwargs)
    body = dict(out.get("extra_body") or {})
    extra_body = extra.pop("extra_body", None) if extra else None
    if extra:
        out.update(extra)
    if isinstance(extra_body, dict):
        body.update(extra_body)
    send_include = (
        not drop_reasoning
        and mode != "off"
        and support.include_reasoning
    )
    if send_include:
        body.setdefault("include_reasoning", True)
    else:
        body.pop("include_reasoning", None)
    if drop_reasoning:
        for key in list(body):
            if key.lower().replace("-", "_") in _REASONING_BODY_KEYS:
                body.pop(key, None)
        for key in list(out):
            if key.lower().replace("-", "_") in _REASONING_PARAMS:
                out.pop(key, None)
    if body:
        out["extra_body"] = body
    else:
        out.pop("extra_body", None)
    return out


def looks_like_reasoning_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in ("reasoning", "thinking", "budget_tokens", "reasoning_effort", "include_reasoning")
    )
