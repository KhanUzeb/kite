"""LiteLLM model adapter with streaming + resolved multi-provider support."""

from __future__ import annotations

import sys
import threading
import time
import warnings
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from kite.agent.events import Event
from kite.agent.exceptions import FormatError
from kite.context.observation import observation_content
from kite.models.cache import PromptCacheManager, parse_cache_usage
from kite.models.reasoning import (
    apply_reasoning,
    detect_reasoning,
    looks_like_reasoning_error,
    looks_like_temperature_reasoning_error,
    split_reasoning,
)
from kite.models.tool_args import repair_tool_arguments
from kite.providers.byos import ensure_oauth_env, is_oauth_provider
from kite.providers.capabilities import model_supports_parallel_tool_calls
from kite.providers.resolve import ResolvedModel
from kite.tools import ToolRegistry


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return ""


_prewarm_lock = threading.Lock()
_prewarm_thread: threading.Thread | None = None


def prewarm_litellm() -> None:
    """Start a background import of litellm (~7s cold on first touch).

    Call once from REPL/run startup while the user reads the banner or
    context gathers — the first turn's `import litellm` then hits warmed
    `sys.modules` (or waits briefly on the import lock if the turn wins
    the race). Idempotent, daemon (never blocks exit), exception-safe.
    """
    global _prewarm_thread
    if "litellm" in sys.modules:
        return
    with _prewarm_lock:
        if "litellm" in sys.modules:
            return
        if _prewarm_thread is not None and _prewarm_thread.is_alive():
            return

        def _import() -> None:
            try:
                import litellm  # noqa: F401
            except Exception:
                pass

        _prewarm_thread = threading.Thread(
            target=_import, daemon=True, name="kite-litellm-prewarm"
        )
        _prewarm_thread.start()


@contextmanager
def _quiet_litellm_usage_serialization():
    """Hide LiteLLM's own ResponsesAPIResponse usage serializer warning.

    LiteLLM's streaming assembler assigns a chat-style usage dict onto
    ``ResponsesAPIResponse.usage`` (typed ``ResponseAPIUsage``) and then calls
    ``model_dump()`` while building its standard-logging payload, so pydantic
    emits ``PydanticSerializationUnexpectedValue`` on every turn from
    ChatGPT-style responses providers. Kite reads token counts straight off the
    stream chunks, so the malformed value never reaches us — this only keeps
    dependency noise out of the transcript.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Pydantic serializer warnings",
            category=UserWarning,
        )
        yield


def estimate_cost_from_usage(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
) -> float:
    """Fallback price from LiteLLM's cost map when a response has no cost.

    Providers (proxies, gateways, streaming assemblers) often omit
    ``_hidden_params.response_cost`` — without a fallback every such turn
    meters $0.000. This prices the counted tokens from LiteLLM's own
    per-token map instead of hardcoding model prices in Kite.
    """
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return 0.0
    try:
        import litellm

        cost_map = getattr(litellm, "model_cost", None) or {}
        name = (model_name or "").strip()
        entry = cost_map.get(name) or {}
        if not entry and "/" in name:
            entry = cost_map.get(name.split("/", 1)[-1]) or {}
        if not entry:
            return 0.0
        input_rate = float(entry.get("input_cost_per_token") or 0.0)
        output_rate = float(entry.get("output_cost_per_token") or 0.0)
        if input_rate <= 0 and output_rate <= 0:
            return 0.0
        cached = max(0, int(cache_read_tokens or 0))
        fresh_prompt = max(0, int(prompt_tokens or 0) - cached)
        cache_rate = entry.get("cache_read_input_token_cost")
        try:
            cache_rate = float(cache_rate) if cache_rate is not None else input_rate
        except (TypeError, ValueError):
            cache_rate = input_rate
        return (
            fresh_prompt * input_rate
            + cached * cache_rate
            + max(0, int(completion_tokens or 0)) * output_rate
        )
    except Exception:
        return 0.0


def extract_reasoning_and_content(delta: Any) -> tuple[str, str]:
    """Split a stream delta / message into (reasoning, answer). Never mix the two."""
    reasoning = ""
    content = ""
    if delta is None:
        return "", ""

    if isinstance(delta, dict):
        reasoning = _as_str(
            delta.get("reasoning_content") or delta.get("reasoning") or delta.get("thinking")
        )
        raw = delta.get("content")
        if isinstance(raw, str):
            content = raw
        elif isinstance(raw, list):
            reasoning, content = _parts_to_channels(raw, reasoning, content)
        return reasoning, content

    for name in ("reasoning_content", "reasoning", "thinking"):
        reasoning += _as_str(getattr(delta, name, None))

    raw = getattr(delta, "content", None)
    if isinstance(raw, str):
        content = raw
    elif isinstance(raw, list):
        reasoning, content = _parts_to_channels(raw, reasoning, content)

    extras = getattr(delta, "provider_specific_fields", None)
    if isinstance(extras, dict) and not reasoning:
        reasoning = _as_str(extras.get("reasoning_content") or extras.get("reasoning"))
    return reasoning, content


def _parts_to_channels(parts: list[Any], reasoning: str, content: str) -> tuple[str, str]:
    for part in parts:
        if isinstance(part, dict):
            ptype = str(part.get("type") or "")
            text = _as_str(part.get("thinking") or part.get("reasoning") or part.get("text") or part.get("content"))
        else:
            ptype = str(getattr(part, "type", "") or "")
            text = _as_str(
                getattr(part, "thinking", None)
                or getattr(part, "reasoning", None)
                or getattr(part, "text", None)
            )
        if ptype in {"thinking", "reasoning", "thought"}:
            reasoning += text
        elif text:
            content += text
    return reasoning, content


def _iter_stream_chunks(
    stream: Any,
    *,
    should_stop: Callable[[], bool],
    poll: Callable[[], None] | None = None,
) -> Any:
    """Yield stream chunks while staying responsive to stop/timeout checks.

    The provider generator blocks on network I/O inside ``__next__`` — the
    consumer's stall/overall timeout checks only run when a chunk arrives, so
    a held-open stream would hang the turn (and swallow Esc) until the HTTP
    client's own read timeout fires. Pumping through a daemon thread keeps the
    consumer polling: ``poll`` runs ~1/s even mid-stall, so stop requests and
    timeouts land promptly.
    """
    import queue as _queue

    _SENTINEL: Any = object()
    box: _queue.Queue = _queue.Queue()

    def _pump() -> None:
        try:
            for chunk in stream:
                box.put(chunk)
        except BaseException as exc:  # noqa: BLE001 — re-raised on the consumer side
            box.put(exc)
        finally:
            box.put(_SENTINEL)

    worker = threading.Thread(target=_pump, daemon=True, name="kite-stream-pump")
    worker.start()
    while True:
        try:
            item = box.get(timeout=1.0)
        except _queue.Empty:
            if poll is not None:
                poll()
            if should_stop():
                return
            continue
        if item is _SENTINEL:
            return
        if isinstance(item, BaseException):
            raise item
        if should_stop():
            return
        yield item


class StreamStalledError(TimeoutError):
    pass


class LitellmModel:
    def __init__(
        self,
        resolved: ResolvedModel,
        registry: ToolRegistry | None = None,
        temperature: float | None = None,
        max_retries: int = 3,
        on_event: Callable[[Event], None] | None = None,
        stream: bool = True,
        reasoning: str = "auto",
        prompt_cache: PromptCacheManager | None = None,
        timeout_seconds: int = 180,
        observation_max_chars: int = 8_000,
    ):
        self.resolved = resolved
        self.model_name = resolved.litellm_model
        self.registry = registry
        self.temperature = temperature
        self.max_retries = max_retries
        self.on_event = on_event
        self.stream = stream
        self.reasoning_mode, self.reasoning_effort = split_reasoning(reasoning)
        remote = None
        if resolved.raw:
            from kite.providers.list_models import RemoteModel

            remote = RemoteModel(id=resolved.model, raw=resolved.raw)
        self.reasoning_support = detect_reasoning(
            resolved.provider,
            resolved.model,
            litellm_model=resolved.litellm_model,
            remote=remote,
        )
        self._parallel_tool_calls = model_supports_parallel_tool_calls(
            provider=resolved.provider,
            model=resolved.model,
            litellm_model=resolved.litellm_model,
            raw=resolved.raw,
        )
        self._drop_reasoning = False
        self.cost = 0.0
        self.last_usage: dict[str, Any] = {}
        self.prompt_cache = prompt_cache
        self.timeout_seconds = timeout_seconds
        self.observation_max_chars = observation_max_chars
        self.should_stop = lambda: False

    def _emit(self, kind: str, **payload: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, payload=payload))  # type: ignore[arg-type]

    def format_message(self, role: str, content: str | list = "", extra: dict | None = None, **kwargs) -> dict:
        msg: dict[str, Any] = {"role": role, "content": content, **kwargs}
        if extra is not None:
            msg["extra"] = extra
        return msg

    def _api_messages(self, messages: list[dict]) -> list[dict]:
        results: dict[str, dict] = {}
        for m in messages:
            if m.get("role") == "tool" and m.get("tool_call_id"):
                results.setdefault(str(m["tool_call_id"]), m)

        api_messages: list[dict] = []
        for m in messages:
            if m.get("role") == "tool":
                continue
            if m.get("role") == "exit":
                continue
            clean = {
                k: v
                for k, v in m.items()
                if k in {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}
                and v is not None
            }
            if m.get("role") == "assistant" and not clean.get("reasoning_content"):
                extra = m.get("extra") if isinstance(m.get("extra"), dict) else {}
                prior = str(extra.get("reasoning") or "").strip()
                if prior:
                    clean["reasoning_content"] = prior
            paired_results: list[dict] = []
            if clean.get("role") == "assistant" and clean.get("tool_calls"):
                tool_calls = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        continue
                    call_id = str(tc.get("id") or "")
                    if call_id:
                        tool_calls.append(tc)
                        result = results.get(call_id)
                        paired_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": str(
                                    result.get("name")
                                    if result
                                    else (tc.get("function") or {}).get("name") or "tool"
                                ),
                                "content": (
                                    result.get("content", "")
                                    if result
                                    else "Tool call was interrupted before producing a result."
                                ),
                            }
                        )
                if tool_calls:
                    clean["tool_calls"] = tool_calls
                else:
                    clean.pop("tool_calls", None)
            if (
                clean.get("role") == "assistant"
                and not clean.get("content")
                and not clean.get("tool_calls")
                and not clean.get("reasoning_content")
            ):
                continue
            api_messages.append(clean)
            api_messages.extend(paired_results)
        return api_messages

    def _completion_kwargs(
        self,
        messages: list[dict],
        *,
        stream: bool,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        o = overrides or {}
        temperature = o["temperature"] if "temperature" in o else self.temperature
        reasoning_mode = o.get("reasoning_mode", self.reasoning_mode)
        reasoning_effort = o.get("reasoning_effort", self.reasoning_effort)
        drop_reasoning = o.get("drop_reasoning", self._drop_reasoning)
        api_messages = self._api_messages(messages)
        if self.prompt_cache is not None:
            api_messages = self.prompt_cache.prepare(api_messages)
        kwargs: dict[str, Any] = {
            **self.resolved.litellm_kwargs(),
            "messages": api_messages,
            # Single attempt — the agent loop owns retries (provider_max_retries
            # with backoff + provider_retry events). Letting LiteLLM retry
            # internally stacks the two loops (3 x 4 attempts), multiplies
            # user-visible delay, and prints one raw error line per attempt
            # that bypasses Kite's formatted error display.
            "num_retries": 0,
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if self.registry is not None:
            kwargs["tools"] = self.registry.tool_schemas()
            kwargs["tool_choice"] = "auto"
            if self._parallel_tool_calls:
                kwargs["parallel_tool_calls"] = True
        if self.timeout_seconds > 0:
            kwargs["timeout"] = float(self.timeout_seconds)
        return apply_reasoning(
            kwargs,
            self.reasoning_support,
            reasoning_mode,
            effort=reasoning_effort,
            drop_reasoning=drop_reasoning,
        )

    def _record_usage(self, usage: Any, hidden: dict[str, Any] | None) -> None:
        parsed = parse_cache_usage(usage, hidden)
        self.last_usage = {
            "prompt_tokens": parsed["prompt_tokens"],
            "completion_tokens": parsed["completion_tokens"],
            "total_tokens": parsed["prompt_tokens"] + parsed["completion_tokens"],
            "cache_read_tokens": parsed["cache_read_tokens"],
            "cache_creation_tokens": parsed["cache_creation_tokens"],
            "cached_tokens": parsed["cached_tokens"],
        }
        if self.prompt_cache is not None:
            self.prompt_cache.record(usage, hidden)
            if self.prompt_cache.last_hit(parsed):
                self._emit(
                    "cache_hit",
                    cache_read=parsed["cache_read_tokens"],
                    cached=parsed["cached_tokens"],
                    cache_creation=parsed["cache_creation_tokens"],
                    session=self.prompt_cache.summary(),
                )

    def _build_assistant(
        self,
        *,
        content: str,
        tool_calls_acc: dict[int, dict[str, Any]],
        cost: float,
        reasoning: str = "",
    ) -> dict:
        actions: list[dict] = []
        tool_calls_out: list[dict] = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            name = tc.get("name") or ""
            raw_args = tc.get("arguments") or "{}"
            args, err = repair_tool_arguments(raw_args)
            if args is None:
                raise FormatError(
                    {
                        "role": "user",
                        "content": err or "Invalid tool arguments JSON",
                        "extra": {"interrupt_type": "FormatError", "cost": cost},
                    }
                )
            if not isinstance(args, dict):
                args = {"value": args}
            actions.append({"tool": name, "arguments": args, "id": tc.get("id")})
            tool_calls_out.append(
                {
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {"name": name, "arguments": raw_args},
                }
            )

        if not actions and not (content or "").strip():
            raise FormatError(
                {
                    "role": "user",
                    "content": "Empty response with no tool calls. Call a tool, or finish via bash submit.",
                    "extra": {"interrupt_type": "FormatError", "cost": cost},
                }
            )

        out: dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
            "extra": {
                "actions": actions,
                "cost": cost,
                "usage": self.last_usage,
                "provider": self.resolved.provider,
                "model": self.resolved.model,
                "timestamp": time.time(),
                "reasoning": reasoning,
            },
        }
        if reasoning.strip():
            # Top-level copy so _api_messages can pass thinking back verbatim.
            out["reasoning_content"] = reasoning
        if tool_calls_out:
            out["tool_calls"] = tool_calls_out
        return out

    def _emit_first_token(self, *, started: float, channel: str, seen: bool) -> bool:
        if seen:
            return True
        ttft_ms = int((time.monotonic() - started) * 1000)
        self._emit("stream_first_token", ttft_ms=ttft_ms, channel=channel)
        return True

    def _finalize_response(
        self,
        *,
        content: str,
        tool_calls_acc: dict[int, dict[str, Any]],
        cost: float,
        reasoning: str,
        ttft_ms: int | None = None,
        include_ttft: bool = False,
    ) -> dict:
        """Shared stream/blocking finalizer: emit ``stream_end`` + build assistant.

        ``include_ttft`` preserves the historical payload difference (stream
        emits ``ttft_ms`` even when None; blocking omits it).
        """
        if include_ttft:
            self._emit(
                "stream_end",
                ok=True,
                chars=len(content),
                tools=len(tool_calls_acc),
                reasoning_chars=len(reasoning),
                ttft_ms=ttft_ms,
            )
        else:
            self._emit(
                "stream_end",
                ok=True,
                chars=len(content),
                tools=len(tool_calls_acc),
                reasoning_chars=len(reasoning),
            )
        return self._build_assistant(
            content=content, tool_calls_acc=tool_calls_acc, cost=cost, reasoning=reasoning
        )

    def _query_stream(self, messages: list[dict], *, overrides: dict[str, Any] | None = None) -> dict:
        import litellm

        self._emit(
            "stream_start",
            provider=self.resolved.provider,
            model=self.resolved.model,
        )
        content = ""
        reasoning = ""
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        cost = 0.0
        started = time.monotonic()
        last_progress = started
        first_token = False
        # Fail fast on stalls: some gateways hold a stream open with no data,
        # and `for chunk in stream` would otherwise block forever (the UI then
        # shows "thinking … running" for tens of minutes and Esc can't land
        # until LiteLLM's own timeout fires). Both bounds raise TimeoutError,
        # which the agent loop treats as transient → bounded retries with
        # backoff → one clean ProviderFault instead of a hang.
        first_token_limit = min(max(float(self.timeout_seconds) - 1.0, 1.0), 30.0) if self.timeout_seconds > 0 else 0.0
        idle_limit = min(float(self.timeout_seconds), 60.0) if self.timeout_seconds > 0 else 0.0

        def _check_timeouts() -> None:
            if self.timeout_seconds <= 0:
                return
            now = time.monotonic()
            if now - started > float(self.timeout_seconds):
                raise TimeoutError(
                    f"stream timed out after {int(now - started)}s without completing"
                )
            stall_limit = idle_limit if first_token else first_token_limit
            if stall_limit > 0 and now - last_progress > stall_limit:
                raise StreamStalledError(
                    f"stream stalled: no data for {int(now - last_progress)}s"
                )

        try:
            with _quiet_litellm_usage_serialization():
                stream = litellm.completion(**self._completion_kwargs(messages, stream=True, overrides=overrides))
                chunks = _iter_stream_chunks(stream, should_stop=self.should_stop, poll=_check_timeouts)
                for chunk in chunks:
                    _check_timeouts()
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        last_progress = time.monotonic()
                        hidden_chunk = getattr(chunk, "_hidden_params", None) or {}
                        self._record_usage(usage, hidden_chunk if isinstance(hidden_chunk, dict) else {})
                        self._emit("stream_usage", **self.last_usage)
                    hidden = getattr(chunk, "_hidden_params", None) or {}
                    if isinstance(hidden, dict) and hidden.get("response_cost") is not None:
                        cost = float(hidden.get("response_cost") or 0.0)

                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = choices[0].delta
                    think_piece, answer_piece = extract_reasoning_and_content(delta)
                    tool_deltas = list(getattr(delta, "tool_calls", None) or [])
                    if think_piece or answer_piece or tool_deltas:
                        last_progress = time.monotonic()
                    if think_piece:
                        first_token = self._emit_first_token(
                            started=started, channel="reasoning", seen=first_token
                        )
                        reasoning += think_piece
                        self._emit("stream_reasoning", text=think_piece)
                    if answer_piece:
                        first_token = self._emit_first_token(
                            started=started, channel="answer", seen=first_token
                        )
                        content += answer_piece
                        self._emit("stream_delta", text=answer_piece)

                    for tc in tool_deltas:
                        idx = int(getattr(tc, "index", 0) or 0)
                        slot = tool_calls_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                        if getattr(tc, "id", None):
                            slot["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            if getattr(fn, "name", None):
                                first_token = self._emit_first_token(
                                    started=started, channel="tool", seen=first_token
                                )
                                slot["name"] = (slot["name"] or "") + fn.name
                                self._emit(
                                    "stream_tool",
                                    index=idx,
                                    name=slot["name"],
                                    partial_args=slot["arguments"],
                                    phase="name",
                                )
                            if getattr(fn, "arguments", None):
                                first_token = self._emit_first_token(
                                    started=started, channel="tool", seen=first_token
                                )
                                slot["arguments"] += fn.arguments
                                self._emit(
                                    "stream_tool",
                                    index=idx,
                                    name=slot["name"],
                                    partial_args=slot["arguments"],
                                    phase="args",
                                )
        except Exception:
            self._emit("stream_end", ok=False)
            raise

        if self.should_stop():
            self._emit("interrupt")

        if cost <= 0:
            usage = self.last_usage if isinstance(self.last_usage, dict) else {}
            cost = estimate_cost_from_usage(
                self.model_name,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
                int(usage.get("cache_read_tokens") or usage.get("cached_tokens") or 0),
            )
        self.cost += cost
        ttft_ms = int((time.monotonic() - started) * 1000) if first_token else None
        return self._finalize_response(
            content=content,
            tool_calls_acc=tool_calls_acc,
            cost=cost,
            reasoning=reasoning,
            ttft_ms=ttft_ms,
            include_ttft=True,
        )

    def _query_blocking(self, messages: list[dict], *, overrides: dict[str, Any] | None = None) -> dict:
        import litellm

        self._emit(
            "stream_start",
            provider=self.resolved.provider,
            model=self.resolved.model,
        )
        with _quiet_litellm_usage_serialization():
            response = litellm.completion(**self._completion_kwargs(messages, stream=False, overrides=overrides))
        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)
        hidden_resp = getattr(response, "_hidden_params", None) or {}
        self._record_usage(usage, hidden_resp if isinstance(hidden_resp, dict) else {})
        cost = float(getattr(response, "_hidden_params", {}).get("response_cost") or 0.0)
        if cost <= 0:
            recorded = self.last_usage if isinstance(self.last_usage, dict) else {}
            cost = estimate_cost_from_usage(
                self.model_name,
                int(recorded.get("prompt_tokens") or 0),
                int(recorded.get("completion_tokens") or 0),
                int(recorded.get("cache_read_tokens") or recorded.get("cached_tokens") or 0),
            )
        self.cost += cost

        think, answer = extract_reasoning_and_content(message)
        if not think:
            think = _as_str(getattr(message, "reasoning_content", None))
        if think:
            self._emit("stream_reasoning", text=think)
        content = answer if answer else _as_str(message.content)
        if content:
            self._emit("stream_delta", text=content)

        tool_calls_acc: dict[int, dict[str, Any]] = {}
        if getattr(message, "tool_calls", None):
            for i, tc in enumerate(message.tool_calls):
                tool_calls_acc[i] = {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                }
        return self._finalize_response(
            content=content,
            tool_calls_acc=tool_calls_acc,
            cost=cost,
            reasoning=think,
        )

    def _query_stream_with_fallback(self, messages: list[dict]) -> dict:
        try:
            return self._query_stream(messages)
        except FormatError:
            raise
        except Exception as e:
            if looks_like_temperature_reasoning_error(e) and self.temperature is not None:
                no_temp = {"temperature": None}
                try:
                    return self._query_stream(messages, overrides=no_temp)
                except Exception:
                    return self._query_blocking(messages, overrides=no_temp)
            if not looks_like_reasoning_error(e):
                raise
            no_reasoning = {"reasoning_mode": "off", "drop_reasoning": True}
            try:
                return self._query_stream(messages, overrides=no_reasoning)
            except Exception:
                return self._query_blocking(messages, overrides=no_reasoning)
    def query(self, messages: list[dict]) -> dict:
        import litellm

        if is_oauth_provider(self.resolved.spec):
            ensure_oauth_env(self.resolved.spec)

        litellm.suppress_debug_info = True
        # LiteLLM logs every failed attempt straight to stderr ("Provider
        # List: …"), bypassing Kite's transcript — on retries the same raw
        # line appears N times with no context. Kite owns error display (one
        # formatted error via RunDisplay), so keep dependency chatter off it.
        import logging as _logging

        for _logger_name in ("litellm", "LiteLLM"):
            try:
                _logging.getLogger(_logger_name).setLevel(_logging.ERROR)
            except Exception:
                pass
        if self.stream:
            return self._query_stream_with_fallback(messages)
        return self._query_blocking(messages)

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        obs: list[dict] = []
        for action, output in zip(actions, outputs, strict=False):
            content = observation_content(output, max_chars=self.observation_max_chars)
            if action.get("id"):
                obs.append(
                    {
                        "role": "tool",
                        "tool_call_id": action["id"],
                        "content": content,
                        "extra": {"raw": output, "timestamp": time.time()},
                    }
                )
            else:
                obs.append(
                    {
                        "role": "user",
                        "content": f"<tool_result tool={action.get('tool')}>\n{content}\n</tool_result>",
                        "extra": {"raw": output, "timestamp": time.time()},
                    }
                )
        return obs
