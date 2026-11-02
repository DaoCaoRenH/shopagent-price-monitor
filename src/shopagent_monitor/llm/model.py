"""Native Responses, Chat Completions and Gemini HTTP backends.

Types are re-exported here so application code has one provider-independent import.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .config import ModelConfig, _resolve_api_key
from .types import (
    ModelBackend,
    ModelContextBudgetError,
    ModelContextLengthError,
    ModelEventStream,
    ModelFailure,
    ModelResponse,
    ModelResponseError,
    ModelStreamEvent,
    ModelToolCall,
    ModelUsage,
)
from .messages import ModelContext
from .streaming import _process_openai_sse
from .serialization import (
    _extract_text,
    _extract_openai_tool_call,
    _nonnegative_int,
    _openai_input,
    _openai_tools,
    _openai_chat_messages,
    _openai_chat_tools,
    _extract_openai_chat_message,
    _gemini_contents,
    _gemini_tools,
    _gemini_reasoning_budget,
    _extract_gemini_text,
    _extract_gemini_tool_call,
    _provider_error_detail,
)

__all__ = [
    "ModelBackend",
    "ModelConfig",
    "ModelContextBudgetError",
    "ModelContextLengthError",
    "ModelEventStream",
    "ModelFailure",
    "ModelResponse",
    "ModelResponseError",
    "ModelStreamEvent",
    "ModelToolCall",
    "ModelUsage",
    "OpenAIResponsesBackend",
    "OpenAIChatCompletionsBackend",
    "GeminiGenerateContentBackend",
    "create_model_backend",
]


def _context_length_failure(detail: str, status: int) -> ModelContextLengthError | None:
    if status not in {400, 413}:
        return None
    match = re.search(r"request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)", detail)
    if match:
        return ModelContextLengthError(
            f"HTTP {status}: {detail}",
            requested_tokens=int(match[1]),
            context_tokens=int(match[2]),
        )
    if any(
        marker in detail.casefold()
        for marker in (
            "context_length_exceeded",
            "maximum context length",
            "context window exceeded",
        )
    ):
        return ModelContextLengthError(f"HTTP {status}: {detail}")
    return None


class OpenAIResponsesBackend:
    def __init__(self, config: ModelConfig, *, api_key: str | None = None) -> None:
        self.config = config
        self.model = config.model
        self._api_key = _resolve_api_key(config, api_key)
        self.last_request_payload: dict[str, Any] | None = None

    def generate(
        self,
        *,
        context: ModelContext,
        max_output_tokens: int,
        require_tool_call: bool = True,
    ) -> ModelResponse:
        if self.config.stream:
            return self.stream(
                context=context,
                max_output_tokens=max_output_tokens,
            ).result(require_tool_call=require_tool_call)

        payload = self._build_payload(
            context=context,
            max_output_tokens=max_output_tokens,
            stream=False,
        )
        self.last_request_payload = payload
        request = self._build_request(payload, stream=False)
        started = time.perf_counter()
        last_error: Exception | None = None
        raw = ""
        for attempt in range(self.config.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except OSError:
                    body = ""
                detail = _provider_error_detail(body)
                context_error = _context_length_failure(detail, exc.code)
                if context_error is not None:
                    raise context_error from exc
                last_error = RuntimeError(f"HTTP {exc.code}: {detail}" if detail else f"HTTP {exc.code}")
                # Retry rate limiting and server-side errors, but fail fast on
                # malformed requests/auth/configuration errors.
                if exc.code < 429 and exc.code < 500:
                    break
                if attempt < self.config.max_retries:
                    time.sleep(min(2.0**attempt, 5.0))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2.0**attempt, 5.0))
        if last_error is not None and not raw:
            raise ModelFailure(
                f"OpenAI Responses request failed after retries: {type(last_error).__name__}: {last_error}"
            ) from last_error
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelResponseError("OpenAI Responses returned invalid JSON envelope") from exc
        text = _extract_text(value)
        tool_call = _extract_openai_tool_call(value)
        if require_tool_call and tool_call is None:
            raise ModelResponseError("OpenAI Responses returned no native tool call")
        usage_value = value.get("usage", {}) if isinstance(value, Mapping) else {}
        usage = ModelUsage(
            input_tokens=_nonnegative_int(usage_value.get("input_tokens")),
            output_tokens=_nonnegative_int(usage_value.get("output_tokens")),
            total_tokens=_nonnegative_int(usage_value.get("total_tokens")),
        )
        return ModelResponse(
            text=text,
            usage=usage,
            response_id=str(value.get("id")) if isinstance(value, Mapping) and value.get("id") else None,
            latency_sec=time.perf_counter() - started,
            tool_call=tool_call,
            raw_response=value,
        )

    def stream(
        self,
        *,
        context: ModelContext,
        max_output_tokens: int,
    ) -> ModelEventStream:
        """Open an OpenAI Responses SSE stream.

        The method is intentionally usable even when ``config.stream`` is
        false.  ``generate`` follows the config switch, while callers that
        explicitly need event-level inspection can opt in for one request.
        """

        payload = self._build_payload(
            context=context,
            max_output_tokens=max_output_tokens,
            stream=True,
        )
        self.last_request_payload = payload
        return ModelEventStream(self._iter_stream_events(payload))

    def _build_payload(
        self,
        *,
        context: ModelContext,
        max_output_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": context.system_prompt,
            "input": _openai_input(context.messages),
            "store": False,
            "max_output_tokens": max(1, int(max_output_tokens)),
        }
        if stream:
            payload["stream"] = True
        if self.config.seed is not None:
            payload["seed"] = int(self.config.seed)
        if context.tools:
            payload.update(
                {
                    "tools": _openai_tools(
                        context.tools,
                        strict=self.config.strict_tool_schema,
                    ),
                    "tool_choice": self.config.tool_choice,
                    "parallel_tool_calls": False,
                }
            )
        if self.config.reasoning_effort != "none" or self.config.send_reasoning_effort_none:
            payload["reasoning"] = {"effort": self.config.reasoning_effort}
        if self.config.reasoning_effort == "none":
            # Responses providers that disable thinking, including DeepSeek's
            # Responses endpoint, accept temperature as the sampling control.
            # Reasoning-enabled models may reject or ignore this field.
            payload["temperature"] = self.config.temperature
        return payload

    def _build_request(self, payload: Mapping[str, Any], *, stream: bool) -> urllib.request.Request:
        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
            # urllib's default Python-urllib user agent is rejected by
            # some OpenAI-compatible gateways before the request reaches
            # the Responses API.
            "User-Agent": "shopagent-price-monitor/0.1",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return urllib.request.Request(
            f"{self.config.base_url}/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _iter_stream_events(self, payload: Mapping[str, Any]):
        request = self._build_request(payload, stream=True)
        started = time.perf_counter()
        last_error: Exception | None = None
        response = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = urllib.request.urlopen(request, timeout=self.config.timeout_sec)
                break
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except OSError:
                    body = ""
                detail = _provider_error_detail(body)
                context_error = _context_length_failure(detail, exc.code)
                if context_error is not None:
                    raise context_error from exc
                last_error = RuntimeError(f"HTTP {exc.code}: {detail}" if detail else f"HTTP {exc.code}")
                # Retry rate limiting and server-side errors, but fail fast on
                # malformed requests/auth/configuration errors.
                if exc.code < 429 and exc.code < 500:
                    break
                if attempt < self.config.max_retries:
                    time.sleep(min(2.0**attempt, 5.0))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2.0**attempt, 5.0))
        if last_error is not None and response is None:
            raise ModelFailure(
                f"OpenAI Responses request failed after retries: {type(last_error).__name__}: {last_error}"
            ) from last_error
        try:
            yield from _process_openai_sse(response, started=started)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


class OpenAIChatCompletionsBackend:
    """OpenAI-compatible Chat Completions backend used by local llama.cpp."""

    def __init__(self, config: ModelConfig, *, api_key: str | None = None) -> None:
        self.config = config
        self.model = config.model
        self._api_key = _resolve_api_key(config, api_key)
        self.last_request_payload: dict[str, Any] | None = None
        if config.stream:
            raise ModelFailure("openai-chat backend does not support streaming")

    def generate(
        self,
        *,
        context: ModelContext,
        max_output_tokens: int,
        require_tool_call: bool = True,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _openai_chat_messages(context.system_prompt, context.messages),
            "temperature": self.config.temperature,
            "max_tokens": max(1, int(max_output_tokens)),
            "stream": False,
        }
        if self.config.reasoning_effort != "none" or self.config.send_reasoning_effort_none:
            payload["reasoning_effort"] = self.config.reasoning_effort
        if self.config.reasoning_effort != "none":
            payload.pop("temperature", None)
        if self.config.seed is not None:
            payload["seed"] = int(self.config.seed)
        if context.tools:
            payload.update(
                {
                    "tools": _openai_chat_tools(context.tools),
                    "tool_choice": self.config.tool_choice,
                    "parallel_tool_calls": False,
                }
            )
        self.last_request_payload = payload
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "shopagent-price-monitor/0.1",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        raw = _request_json_with_retries(
            request,
            timeout_sec=self.config.timeout_sec,
            max_retries=self.config.max_retries,
            provider_name="OpenAI Chat Completions",
        )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelResponseError("OpenAI Chat Completions returned invalid JSON envelope") from exc
        text, tool_call = _extract_openai_chat_message(value)
        if require_tool_call and tool_call is None:
            raise ModelResponseError("OpenAI Chat Completions returned no native tool call")
        usage_value = value.get("usage", {}) if isinstance(value, Mapping) else {}
        return ModelResponse(
            text=text,
            usage=ModelUsage(
                input_tokens=_nonnegative_int(usage_value.get("prompt_tokens")),
                output_tokens=_nonnegative_int(usage_value.get("completion_tokens")),
                total_tokens=_nonnegative_int(usage_value.get("total_tokens")),
            ),
            response_id=str(value.get("id")) if isinstance(value, Mapping) and value.get("id") else None,
            latency_sec=time.perf_counter() - started,
            tool_call=tool_call,
            raw_response=value,
        )


class GeminiGenerateContentBackend:
    """Native Google Gemini ``models/{model}:generateContent`` backend.

    Gemini API keys are sent through the standard ``?key=`` query parameter
    and are read from ``GEMINI_API_KEY`` by default.  The backend declares the
    six domain tools and converts Gemini's native ``functionCall`` response
    into the provider-neutral tool-call contract expected by the planner.
    """

    def __init__(self, config: ModelConfig, *, api_key: str | None = None) -> None:
        self.config = config
        self.model = config.model
        self._api_key = _resolve_api_key(config, api_key)
        self.last_request_payload: dict[str, Any] | None = None

    def generate(
        self,
        *,
        context: ModelContext,
        max_output_tokens: int,
        require_tool_call: bool = True,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "contents": _gemini_contents(context.messages),
            "systemInstruction": {"parts": [{"text": context.system_prompt}]},
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": max(1, int(max_output_tokens)),
            },
        }
        if self.config.seed is not None:
            # The episode seed is uint32; Gemini's generationConfig.seed is int32.
            payload["generationConfig"]["seed"] = int(self.config.seed) % (1 << 31)
        if context.tools:
            payload.update(
                {
                    "tools": _gemini_tools(context.tools),
                    "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
                }
            )
        if self.config.reasoning_budget is not None:
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": self.config.reasoning_budget}
        elif self.config.reasoning_effort != "none":
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": _gemini_reasoning_budget(self.config.reasoning_effort)
            }
        self.last_request_payload = payload
        encoded_model = urllib.parse.quote(self.model, safe="")
        endpoint = f"{self.config.base_url}/models/{encoded_model}:generateContent"
        if self._api_key:
            endpoint += f"?key={urllib.parse.quote(self._api_key, safe='')}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        last_error: Exception | None = None
        raw = ""
        for attempt in range(self.config.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except OSError:
                    body = ""
                detail = _provider_error_detail(body)
                context_error = _context_length_failure(detail, exc.code)
                if context_error is not None:
                    raise context_error from exc
                last_error = RuntimeError(f"HTTP {exc.code}: {detail}" if detail else f"HTTP {exc.code}")
                if exc.code < 429 and exc.code < 500:
                    break
                if attempt < self.config.max_retries:
                    time.sleep(min(2.0**attempt, 5.0))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2.0**attempt, 5.0))
        if last_error is not None and not raw:
            raise ModelFailure(f"Gemini generateContent request failed after retries: {last_error}") from last_error
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelResponseError("Gemini generateContent returned invalid JSON envelope") from exc
        text = _extract_gemini_text(value)
        tool_call = _extract_gemini_tool_call(value)
        if require_tool_call and tool_call is None:
            raise ModelResponseError("Gemini generateContent returned no native tool call")
        usage_value = value.get("usageMetadata", {}) if isinstance(value, Mapping) else {}
        usage = ModelUsage(
            input_tokens=_nonnegative_int(usage_value.get("promptTokenCount")),
            output_tokens=_nonnegative_int(usage_value.get("candidatesTokenCount")),
            total_tokens=_nonnegative_int(usage_value.get("totalTokenCount")),
        )
        response_id = None
        if isinstance(value, Mapping):
            raw_id = value.get("responseId") or value.get("response_id")
            if raw_id:
                response_id = str(raw_id)
        return ModelResponse(
            text=text,
            usage=usage,
            response_id=response_id,
            latency_sec=time.perf_counter() - started,
            tool_call=tool_call,
            raw_response=value,
        )


def create_model_backend(config: ModelConfig) -> ModelBackend:
    """Create the configured provider without changing agent code."""

    if config.provider == "gemini":
        return GeminiGenerateContentBackend(config)
    if config.provider == "openai-chat":
        return OpenAIChatCompletionsBackend(config)
    return OpenAIResponsesBackend(config)


def _request_json_with_retries(
    request: urllib.request.Request,
    *,
    timeout_sec: float,
    max_retries: int,
    provider_name: str,
) -> str:
    raw = ""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except OSError:
                body = ""
            detail = _provider_error_detail(body)
            context_error = _context_length_failure(detail, exc.code)
            if context_error is not None:
                raise context_error from exc
            last_error = RuntimeError(f"HTTP {exc.code}: {detail}" if detail else f"HTTP {exc.code}")
            if exc.code < 429 and exc.code < 500:
                break
            if attempt < max_retries:
                time.sleep(min(2.0**attempt, 5.0))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(min(2.0**attempt, 5.0))
    if last_error is not None and not raw:
        raise ModelFailure(
            f"{provider_name} request failed after retries: {type(last_error).__name__}: {last_error}"
        ) from last_error
    return raw
