"""Provider-neutral model responses, stream events and failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from .messages import ModelContext


class ModelFailure(RuntimeError):
    pass


class ModelResponseError(ModelFailure):
    pass


class ModelContextLengthError(ModelFailure):
    reason_code = "context_length_exceeded"

    def __init__(self, message: str, *, requested_tokens: int | None = None, context_tokens: int | None = None) -> None:
        super().__init__(message)
        self.requested_tokens = requested_tokens
        self.context_tokens = context_tokens


class ModelContextBudgetError(ModelFailure):
    reason_code = "protected_context_overflow"


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ModelToolCall:
    """A provider-neutral native function/tool call returned by the model."""

    name: str
    arguments: Mapping[str, Any]
    call_id: str | None = None
    thought_signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = {"name": self.name, "arguments": dict(self.arguments), "call_id": self.call_id}
        if self.thought_signature is not None:
            value["thought_signature"] = self.thought_signature
        return value


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: ModelUsage = ModelUsage()
    response_id: str | None = None
    latency_sec: float = 0.0
    tool_call: ModelToolCall | None = None
    # Parsed provider envelope retained for trace/replay. It is never used as
    # model context and does not contain the request credential.
    raw_response: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ModelStreamEvent:
    """Provider-neutral event emitted while a model response is streaming.

    ``arguments`` is deliberately best-effort during ``toolcall_delta``.  A
    caller must wait for ``toolcall_end`` (and ultimately ``done``) before
    executing a native tool call.  This mirrors the Responses event contract
    and prevents an incomplete JSON fragment from reaching ``ToolExecutor``.
    """

    type: str
    text_delta: str = ""
    thinking_delta: str = ""
    arguments_delta: str = ""
    tool_name: str | None = None
    arguments: Mapping[str, Any] | None = None
    tool_call: ModelToolCall | None = None
    response: ModelResponse | None = None
    response_id: str | None = None
    raw_event: Mapping[str, Any] | None = None
    error: str | None = None


class ModelEventStream:
    """Iterate safe stream events, then retrieve the completed model response."""

    def __init__(self, source: Any) -> None:
        self._source = iter(source)
        self._finished = False
        self._response: ModelResponse | None = None
        self._error: Exception | None = None

    def __iter__(self):
        while not self._finished:
            try:
                event = next(self._source)
            except StopIteration:
                self._finished = True
                break
            except Exception as exc:
                self._finished = True
                self._error = exc
                raise
            if event.type == "done":
                self._response = event.response
                self._finished = True
            elif event.type == "error":
                self._error = ModelFailure(event.error or "model stream failed")
                self._finished = True
            yield event

    def result(self, *, require_tool_call: bool = True) -> ModelResponse:
        """Consume remaining events and return the final response."""

        if not self._finished:
            for _ in self:
                pass
        if self._error is not None:
            if isinstance(self._error, ModelFailure):
                raise self._error
            raise ModelFailure(f"model stream failed: {self._error}") from self._error
        if self._response is None:
            raise ModelResponseError("model stream ended without a completed response")
        if require_tool_call and self._response.tool_call is None:
            raise ModelResponseError("OpenAI Responses returned no native tool call")
        return self._response

    def close(self) -> None:
        """Release an in-flight HTTP response when a consumer cancels."""
        close = getattr(self._source, "close", None)
        if callable(close):
            close()
        self._finished = True


class ModelBackend(Protocol):
    model: str

    def generate(
        self,
        *,
        context: ModelContext,
        max_output_tokens: int,
        require_tool_call: bool = True,
    ) -> ModelResponse: ...
