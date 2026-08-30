"""LiteLLM model adapter with streaming + resolved multi-provider support."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from kite.agent.events import Event
from kite.agent.exceptions import FormatError
from kite.models.reasoning import apply_reasoning, detect_reasoning, looks_like_reasoning_error, split_reasoning
from kite.models.cache import PromptCacheManager, parse_cache_usage
from kite.providers.resolve import ResolvedModel
from kite.tools import ToolRegistry


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return ""


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


class LitellmModel:
    def __init__(
        self,
        resolved: ResolvedModel,
        registry: ToolRegistry | None = None,
        temperature: float = 0.0,
        max_retries: int = 2,
        on_event: Callable[[Event], None] | None = None,
        stream: bool = True,
        reasoning: str = "auto",
        prompt_cache: PromptCacheManager | None = None,
        timeout_seconds: int = 180,
    ):
        self.resolved = resolved
        self.model_name = resolved.litellm_model
        self.registry = registry
        self.temperature = temperature
        self.max_retries = max_retries
        self.on_event = on_event
        self.stream = stream
        self.reasoning_mode, self.reasoning_effort = split_reasoning(reasoning)
        self.reasoning_support = detect_reasoning(
            resolved.provider,
            resolved.model,
            litellm_model=resolved.litellm_model,
        )
        self._drop_reasoning = False
        self.cost = 0.0
        self.last_usage: dict[str, Any] = {}
        self.prompt_cache = prompt_cache
        self.timeout_seconds = timeout_seconds
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
        api_messages = []
        for m in messages:
            if m.get("role") == "exit":
                continue
            clean = {
                k: v
                for k, v in m.items()
                if k in {"role", "content", "tool_calls", "tool_call_id", "name"} and v is not None
            }
            if clean.get("role") == "assistant" and not clean.get("content") and not clean.get("tool_calls"):
                continue
            api_messages.append(clean)
        return api_messages

    def _completion_kwargs(self, messages: list[dict], *, stream: bool) -> dict[str, Any]:
        api_messages = self._api_messages(messages)
        if self.prompt_cache is not None:
            api_messages = self.prompt_cache.prepare(api_messages)
        kwargs: dict[str, Any] = {
            **self.resolved.litellm_kwargs(),
            "messages": api_messages,
            "temperature": self.temperature,
            "num_retries": self.max_retries,
            "stream": stream,
        }
        if self.registry is not None:
            kwargs["tools"] = self.registry.openai_schemas()
            kwargs["tool_choice"] = "auto"
        if self.timeout_seconds > 0:
            kwargs["timeout"] = float(self.timeout_seconds)
        return apply_reasoning(
            kwargs,
            self.reasoning_support,
            self.reasoning_mode,
            effort=self.reasoning_effort,
            drop_reasoning=self._drop_reasoning,
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
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError as e:
                raise FormatError(
                    {
                        "role": "user",
                        "content": f"Invalid tool arguments JSON: {e}",
                        "extra": {"interrupt_type": "FormatError", "cost": cost},
                    }
                ) from e
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
        if tool_calls_out:
            out["tool_calls"] = tool_calls_out
        return out

    def _query_stream(self, messages: list[dict]) -> dict:
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

        try:
            stream = litellm.completion(**self._completion_kwargs(messages, stream=True))
            for chunk in stream:
                if self.should_stop():
                    self._emit("interrupt")
                    break
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    hidden_chunk = getattr(chunk, "_hidden_params", None) or {}
                    self._record_usage(usage, hidden_chunk if isinstance(hidden_chunk, dict) else {})
                hidden = getattr(chunk, "_hidden_params", None) or {}
                if isinstance(hidden, dict) and hidden.get("response_cost") is not None:
                    cost = float(hidden.get("response_cost") or 0.0)

                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = choices[0].delta
                think_piece, answer_piece = extract_reasoning_and_content(delta)
                if think_piece:
                    reasoning += think_piece
                    self._emit("stream_reasoning", text=think_piece)
                if answer_piece:
                    content += answer_piece
                    self._emit("stream_delta", text=answer_piece)

                for tc in getattr(delta, "tool_calls", None) or []:
                    idx = int(getattr(tc, "index", 0) or 0)
                    slot = tool_calls_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = (slot["name"] or "") + fn.name
                            self._emit("stream_tool", name=slot["name"], partial_args=slot["arguments"])
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments
                            self._emit("stream_tool", name=slot["name"], partial_args=slot["arguments"])
        except Exception:
            self._emit("stream_end", ok=False)
            raise

        self.cost += cost
        self._emit("stream_end", ok=True, chars=len(content), tools=len(tool_calls_acc), reasoning_chars=len(reasoning))
        return self._build_assistant(content=content, tool_calls_acc=tool_calls_acc, cost=cost, reasoning=reasoning)

    def _query_blocking(self, messages: list[dict]) -> dict:
        import litellm

        self._emit(
            "stream_start",
            provider=self.resolved.provider,
            model=self.resolved.model,
        )
        response = litellm.completion(**self._completion_kwargs(messages, stream=False))
        choice = response.choices[0]
        message = choice.message
        usage = getattr(response, "usage", None)
        hidden_resp = getattr(response, "_hidden_params", None) or {}
        self._record_usage(usage, hidden_resp if isinstance(hidden_resp, dict) else {})
        cost = float(getattr(response, "_hidden_params", {}).get("response_cost") or 0.0)
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
        self._emit("stream_end", ok=True, chars=len(content), tools=len(tool_calls_acc), reasoning_chars=len(think))
        return self._build_assistant(
            content=content,
            tool_calls_acc=tool_calls_acc,
            cost=cost,
            reasoning=think,
        )

    def query(self, messages: list[dict]) -> dict:
        import litellm

        # Quiet LiteLLM's banner / provider tips on errors.
        litellm.suppress_debug_info = True
        if self.stream:
            try:
                return self._query_stream(messages)
            except FormatError:
                raise
            except Exception as e:
                if looks_like_reasoning_error(e):
                    self.reasoning_mode = "off"
                    self._drop_reasoning = True
                    try:
                        return self._query_stream(messages)
                    except Exception:
                        return self._query_blocking(messages)
                return self._query_blocking(messages)
        return self._query_blocking(messages)

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        obs: list[dict] = []
        for action, output in zip(actions, outputs):
            content = output.get("output") or output.get("error") or json.dumps(output, default=str)
            if len(content) > 12_000:
                content = content[:6_000] + "\n...<elided>...\n" + content[-4_000:]
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
