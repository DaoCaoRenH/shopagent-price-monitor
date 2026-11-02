"""Bounded model requests, safe stream metadata, and retries of one model turn."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ..llm.context_budget import ContextTokenCounter
from ..llm.messages import ModelContext
from ..llm.model import ModelBackend, ModelConfig, ModelContextBudgetError, ModelResponse
from .model_errors import connection_error
from .search_progress import SearchCancelled


DEFAULT_CONTEXT_TOKENS = 24576
CONTEXT_MARGIN_TOKENS = 256


def generate_bounded(
    backend: ModelBackend,
    *,
    context: ModelContext,
    max_output_tokens: int,
    max_context_tokens: int,
    max_retries: int = 0,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: threading.Event | None = None,
    require_tool_call: bool = True,
) -> ModelResponse:
    # Count instructions, tool schemas and the full conversation, reserving output as well.
    estimated_input = ContextTokenCounter().context(context)
    if estimated_input + max_output_tokens + CONTEXT_MARGIN_TOKENS > max_context_tokens:
        raise ModelContextBudgetError(
            f"上下文超过客户端上限：估算输入 {estimated_input} Token + 输出预留 {max_output_tokens}"
            f" + 安全余量 {CONTEXT_MARGIN_TOKENS}，超过 {max_context_tokens} Token。"
            "请缩短输入，或在服务端支持的范围内提高上下文长度。"
        )
    config = getattr(backend, "config", None)
    if not isinstance(config, ModelConfig):
        config = ModelConfig(provider="openai-responses", model="unknown", api_key_required=False)

    def check_cancelled():
        if cancelled is not None and cancelled.is_set():
            raise SearchCancelled()

    def publish(**event):
        check_cancelled()
        if on_progress is not None:
            on_progress(event)

    for attempt in range(max_retries + 1):
        check_cancelled()
        stream = None
        try:
            if config.stream and config.provider == "openai-responses":
                stream = backend.stream(context=context, max_output_tokens=max_output_tokens)
                first = True
                received = 0
                for event in stream:
                    check_cancelled()
                    if first:
                        publish(phase="connected")
                        first = False
                    received += len(event.thinking_delta) + len(event.text_delta) + len(event.arguments_delta)
                    phase = {
                        "thinking_start": "generating",
                        "thinking_delta": "generating",
                        "text_start": "receiving",
                        "text_delta": "receiving",
                        "toolcall_start": "tool_arguments",
                        "toolcall_delta": "tool_arguments",
                        "toolcall_end": "tool_received",
                        "done": "validating",
                    }.get(event.type)
                    if phase:
                        # No text, thought, argument fragments, or raw events cross this boundary.
                        publish(phase=phase, received_chars=received)
                return stream.result(require_tool_call=require_tool_call)
            result = backend.generate(
                context=context, max_output_tokens=max_output_tokens, require_tool_call=require_tool_call
            )
            check_cancelled()
            return result
        except SearchCancelled:
            raise
        except Exception as exc:
            check_cancelled()
            diagnostic = connection_error(exc, config)["error"]
            retryable = diagnostic["kind"] in {"timeout", "network_error", "connection_refused", "dns_error"}
            retryable |= diagnostic["http_status"] in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt == max_retries:
                raise
            if stream is not None:
                stream.close()
                stream = None
            delay = min(2**attempt, 5)
            publish(
                phase="retry", attempt=attempt + 1, retry_limit=max_retries, delay_sec=delay, reason=diagnostic["kind"]
            )
            # Each attempt gets the same immutable context. No domain tool has run yet.
            if cancelled is not None:
                if cancelled.wait(delay):
                    raise SearchCancelled()
            else:
                time.sleep(delay)
        finally:
            if stream is not None:
                stream.close()
    raise AssertionError("unreachable")
