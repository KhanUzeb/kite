"""LLM compaction via OpenRouter free-tier, with a deterministic fallback.

Free models are listed live from OpenRouter (zero price or `:free` in the
payload). Nothing is hardcoded; if the catalog is empty we skip the LLM call.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kite.config import UserConfig
from kite.context.window import deterministic_summary
from kite.providers.list_models import RemoteModel, list_free_models

COMPACTION_SYSTEM = """You compress a coding-agent transcript into a dense brief.
Keep: decisions, file paths touched, errors, user constraints, remaining work, test failures.
Drop: raw tool dumps, repeated code, chit-chat, duplicated paths.
If a ## Preserved facts block is present in the input, integrate those bullets — do not drop them.
Write in third person. No preamble. Max 700 words."""

_MAX_TRIES = 3


def _rank_free(model: RemoteModel) -> tuple[int, int, int, str]:
    """Prefer explicit :free, then smaller windows (cheaper summary calls)."""
    explicit = 0 if model.id.lower().endswith(":free") else 1
    window = model.context_window if isinstance(model.context_window, int) and model.context_window > 0 else 10**9
    reasoning = model.raw.get("reasoning") if isinstance(model.raw, dict) else None
    mandatory = 1 if isinstance(reasoning, dict) and reasoning.get("mandatory") else 0
    return (mandatory, explicit, window, model.id.lower())


def list_compaction_models(config: UserConfig | None = None) -> list[RemoteModel]:
    """Live OpenRouter free-tier chat models, ranked for a short summary call."""
    cfg = config or UserConfig.load()
    result = list_free_models("openrouter", config=cfg)
    if not result.ok:
        return []
    rows = list(result.models)
    rows.sort(key=_rank_free)
    return rows


def pick_openrouter_free(config: UserConfig | None = None) -> str | None:
    """Return a live free model id (no `openrouter/` prefix), or a user override."""
    cfg = config or UserConfig.load()
    override = getattr(cfg, "compaction_model", None) or ""
    if override:
        return str(override).removeprefix("openrouter/")
    models = list_compaction_models(cfg)
    return models[0].id if models else None


def _try_complete(resolved: Any, transcript: str) -> str | None:
    kwargs: dict[str, Any] = {
        **resolved.litellm_kwargs(),
        "messages": [
            {"role": "system", "content": COMPACTION_SYSTEM},
            {"role": "user", "content": transcript},
        ],
        "max_tokens": 900,
        "timeout": 40,
        "num_retries": 0,
        "stream": False,
    }
    try:
        import litellm

        litellm.suppress_debug_info = True
        response = litellm.completion(**kwargs)
        content = (response.choices[0].message.content or "").strip()
        return content or None
    except Exception:
        return None


def llm_summarize(
    messages: list[dict],
    *,
    config: UserConfig | None = None,
) -> str | None:
    cfg = config or UserConfig.load()
    if not getattr(cfg, "compaction_use_llm", True):
        return None
    try:
        from kite.providers.resolve import missing_credentials, resolve_model
    except Exception:
        return None

    provider = (getattr(cfg, "compaction_provider", None) or "openrouter").strip() or "openrouter"
    transcript = deterministic_summary(messages, max_chars=18_000)

    candidates: list[str] = []
    override = getattr(cfg, "compaction_model", None) or ""
    if override:
        candidates.append(str(override).removeprefix("openrouter/"))
    elif provider == "openrouter":
        candidates.extend(m.id for m in list_compaction_models(cfg)[:_MAX_TRIES])
    else:
        if getattr(cfg, "compaction_model", None):
            candidates.append(str(cfg.compaction_model).removeprefix(f"{provider}/"))

    seen: set[str] = set()
    for model in candidates:
        if not model or model in seen:
            continue
        seen.add(model)
        try:
            resolved = resolve_model(provider=provider, model=model, config=cfg)
        except Exception:
            continue
        if missing_credentials(resolved):
            return None
        text = _try_complete(resolved, transcript)
        if text:
            return text
    return None


def make_summarizer(config: UserConfig | None = None) -> Callable[[list[dict]], str]:
    cfg = config or UserConfig.load()

    def summarize(dropped: list[dict]) -> str:
        text = llm_summarize(dropped, config=cfg)
        if text:
            return text
        return deterministic_summary(dropped)

    return summarize
