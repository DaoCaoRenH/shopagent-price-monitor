"""Aggregate Responses SSE; only a completed validated call can be executed."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any, Mapping
from .types import ModelResponse, ModelResponseError, ModelStreamEvent, ModelToolCall, ModelUsage
from .serialization import _extract_text, _extract_openai_tool_call, _parse_tool_arguments, _nonnegative_int


@dataclass
class _StreamingToolState:
    output_index: int
    name: str = ""
    call_id: str | None = None
    partial_json: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    finalized: bool = False


def _iter_response_lines(response: Any):
    """Yield text lines from urllib responses and small test doubles."""

    try:
        source = iter(response)
    except TypeError:
        raw = response.read()
        source = iter(raw.splitlines(keepends=True) if isinstance(raw, bytes) else str(raw).splitlines(True))
    pending = ""
    for chunk in source:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        pending += str(chunk)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield line.rstrip("\r")
    if pending:
        yield pending.rstrip("\r")


def _iter_sse_events(response: Any):
    """Parse OpenAI Responses SSE frames without depending on an SDK."""

    event_name = ""
    data_lines: list[str] = []

    def flush():
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = ""
            return None
        data = "\n".join(data_lines).strip()
        current_name = event_name
        event_name = ""
        data_lines = []
        if data == "[DONE]":
            return {"type": "_done"}
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            return {
                "type": current_name or "error",
                "message": "OpenAI Responses emitted invalid SSE JSON",
                "data": data[:500],
            }
        if isinstance(value, Mapping):
            result = dict(value)
            if not result.get("type") and current_name:
                result["type"] = current_name
            return result
        return {
            "type": current_name or "error",
            "message": "OpenAI Responses SSE data was not an object",
        }

    for line in _iter_response_lines(response):
        if line == "":
            event = flush()
            if event is not None:
                yield event
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        else:
            # A few compatible gateways send JSONL while accepting
            # ``stream=true``.  Treat a bare JSON line as one SSE frame.
            data_lines.append(line)
    event = flush()
    if event is not None:
        yield event


def _streaming_output_index(event: Mapping[str, Any]) -> int:
    try:
        return int(event.get("output_index", 0))
    except (TypeError, ValueError):
        return 0


def _streaming_usage(value: Any) -> ModelUsage:
    if not isinstance(value, Mapping):
        return ModelUsage()
    return ModelUsage(
        input_tokens=_nonnegative_int(value.get("input_tokens")),
        output_tokens=_nonnegative_int(value.get("output_tokens")),
        total_tokens=_nonnegative_int(value.get("total_tokens")),
    )


def _streaming_partial_json(value: Any) -> dict[str, Any]:
    """Best-effort parsing for display-only partial function arguments."""

    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    candidate = value.strip()
    in_string = False
    escaped = False
    stack: list[str] = []
    for char in candidate:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    if in_string:
        candidate += '"'
    stripped = candidate.rstrip()
    if stripped.endswith(":"):
        candidate = stripped + "null"
    elif stripped.endswith(","):
        candidate = stripped[:-1]
    candidate += "".join(reversed(stack))
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _process_openai_sse(response: Any, *, started: float):
    """Convert Responses events into provider-neutral model events."""

    text_parts: list[str] = []
    thinking_started = False
    text_started = False
    response_id: str | None = None
    terminal_response: Mapping[str, Any] | None = None
    usage = ModelUsage()
    tools: dict[int, _StreamingToolState] = {}
    terminal_seen = False

    def get_tool(
        event: Mapping[str, Any],
        item: Mapping[str, Any] | None = None,
        *,
        final_arguments: bool = False,
    ) -> _StreamingToolState:
        index = _streaming_output_index(event)
        state = tools.get(index)
        if state is None:
            state = _StreamingToolState(output_index=index)
            tools[index] = state
        source = item if isinstance(item, Mapping) else event
        name = source.get("name")
        call_id = source.get("call_id") or source.get("id")
        arguments = source.get("arguments")
        if isinstance(name, str) and name:
            if state.name and state.name != name:
                raise ModelResponseError("OpenAI Responses changed the tool name during one tool call")
            state.name = name
        if call_id and not state.call_id:
            state.call_id = str(call_id)
        if arguments is not None and (final_arguments or not state.partial_json):
            if final_arguments:
                parsed = _parse_tool_arguments(arguments)
                if parsed is None:
                    raise ModelResponseError("OpenAI Responses returned invalid completed tool arguments")
                if state.finalized and parsed != state.arguments:
                    raise ModelResponseError("OpenAI Responses returned conflicting completed tool arguments")
            state.partial_json = str(arguments) if not isinstance(arguments, Mapping) else json.dumps(arguments)
            state.arguments = _streaming_partial_json(arguments)
        return state

    def finish_tool(state: _StreamingToolState, raw_event: Mapping[str, Any]):
        if state.finalized:
            return None
        # Partial JSON repair is only for display. Execution requires the exact
        # completed JSON object, including a tool name supplied by the provider.
        arguments = _parse_tool_arguments(state.partial_json)
        if not state.name.strip() or arguments is None:
            raise ModelResponseError(
                "OpenAI Responses returned an invalid completed tool call (missing name or invalid JSON object)"
            )
        state.arguments = arguments
        state.finalized = True
        call = ModelToolCall(
            name=state.name.strip(),
            arguments=dict(state.arguments),
            call_id=state.call_id,
        )
        return ModelStreamEvent(
            type="toolcall_end",
            tool_name=call.name,
            arguments=call.arguments,
            tool_call=call,
            response_id=response_id,
            raw_event=dict(raw_event),
        )

    for raw_event in _iter_sse_events(response):
        event = dict(raw_event) if isinstance(raw_event, Mapping) else {}
        event_type = str(event.get("type", ""))
        if event_type == "_done":
            continue
        # Some compatibility gateways return one JSON envelope despite
        # accepting stream=true.  Treat it as a completed response.
        if not event_type and ("output" in event or "output_text" in event):
            event_type = "response.completed"
            event = {"type": event_type, "response": event}

        if event_type == "response.created":
            created = event.get("response")
            if isinstance(created, Mapping) and created.get("id"):
                response_id = str(created["id"])
            elif event.get("id"):
                response_id = str(event["id"])
        elif event_type == "response.output_item.added":
            item = event.get("item")
            if not isinstance(item, Mapping):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                state = get_tool(event, item)
                yield ModelStreamEvent(
                    type="toolcall_start",
                    tool_name=state.name,
                    arguments=dict(state.arguments),
                    response_id=response_id,
                    raw_event=event,
                )
            elif item_type == "message":
                text_started = True
                yield ModelStreamEvent(type="text_start", response_id=response_id, raw_event=event)
            elif item_type == "reasoning":
                thinking_started = True
                yield ModelStreamEvent(type="thinking_start", response_id=response_id, raw_event=event)
        elif event_type in {"response.output_text.delta", "response.refusal.delta"}:
            delta = str(event.get("delta", ""))
            if not text_started:
                text_started = True
                yield ModelStreamEvent(type="text_start", response_id=response_id, raw_event=event)
            text_parts.append(delta)
            yield ModelStreamEvent(
                type="text_delta",
                text_delta=delta,
                response_id=response_id,
                raw_event=event,
            )
        elif event_type in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            delta = str(event.get("delta", ""))
            if not thinking_started:
                thinking_started = True
                yield ModelStreamEvent(type="thinking_start", response_id=response_id, raw_event=event)
            yield ModelStreamEvent(
                type="thinking_delta",
                thinking_delta=delta,
                response_id=response_id,
                raw_event=event,
            )
        elif event_type == "response.function_call_arguments.delta":
            state = get_tool(event)
            delta = str(event.get("delta", ""))
            state.partial_json += delta
            state.arguments = _streaming_partial_json(state.partial_json)
            yield ModelStreamEvent(
                type="toolcall_delta",
                arguments_delta=delta,
                tool_name=state.name,
                arguments=dict(state.arguments),
                response_id=response_id,
                raw_event=event,
            )
        elif event_type == "response.function_call_arguments.done":
            state = get_tool(event)
            arguments = event.get("arguments", state.partial_json)
            state.partial_json = str(arguments) if not isinstance(arguments, Mapping) else json.dumps(arguments)
            state.arguments = _streaming_partial_json(arguments)
            finished = finish_tool(state, event)
            if finished is not None:
                yield finished
        elif event_type == "response.output_item.done":
            item = event.get("item")
            if not isinstance(item, Mapping):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                state = get_tool(event, item, final_arguments=True)
                finished = finish_tool(state, event)
                if finished is not None:
                    yield finished
            elif item_type == "message":
                if text_started:
                    yield ModelStreamEvent(
                        type="text_end", text_delta="".join(text_parts), response_id=response_id, raw_event=event
                    )
                    text_started = False
            elif item_type == "reasoning":
                if thinking_started:
                    yield ModelStreamEvent(type="thinking_end", response_id=response_id, raw_event=event)
                    thinking_started = False
        elif event_type in {"response.completed", "response.incomplete"}:
            terminal_seen = True
            terminal = event.get("response")
            terminal_response = dict(terminal) if isinstance(terminal, Mapping) else {}
            if event_type == "response.incomplete" or terminal_response.get("status") == "incomplete":
                raise ModelResponseError(
                    "OpenAI Responses generation incomplete: "
                    + str(terminal_response.get("incomplete_details") or "missing completion")
                )
            if terminal_response.get("id"):
                response_id = str(terminal_response["id"])
            usage = _streaming_usage(terminal_response.get("usage"))
            if not text_parts:
                extracted = _extract_text(terminal_response)
                if extracted:
                    text_parts.append(extracted)
            output = terminal_response.get("output", [])
            if isinstance(output, list):
                for output_index, item in enumerate(output):
                    if not isinstance(item, Mapping) or item.get("type") != "function_call":
                        continue
                    state = get_tool(
                        {"output_index": item.get("output_index", output_index)},
                        item,
                        final_arguments=True,
                    )
                    finished = finish_tool(state, event)
                    if finished is not None:
                        yield finished
            if text_started:
                yield ModelStreamEvent(
                    type="text_end", text_delta="".join(text_parts), response_id=response_id, raw_event=event
                )
                text_started = False
            if thinking_started:
                yield ModelStreamEvent(type="thinking_end", response_id=response_id, raw_event=event)
                thinking_started = False
            selected_tool = next((state for state in tools.values() if state.finalized and state.name), None)
            tool_call = None
            if selected_tool is not None:
                tool_call = ModelToolCall(
                    name=selected_tool.name,
                    arguments=dict(selected_tool.arguments),
                    call_id=selected_tool.call_id,
                )
            elif terminal_response:
                tool_call = _extract_openai_tool_call(terminal_response)
            final = ModelResponse(
                text="".join(text_parts),
                usage=usage,
                response_id=response_id,
                latency_sec=time.perf_counter() - started,
                tool_call=tool_call,
                raw_response=terminal_response,
            )
            yield ModelStreamEvent(type="done", response=final, response_id=response_id, raw_event=event)
            return
        elif event_type in {"error", "response.failed"}:
            error_value = event.get("message")
            if not error_value and isinstance(event.get("response"), Mapping):
                error = event["response"].get("error")
                if isinstance(error, Mapping):
                    error_value = error.get("message") or error.get("code")
            yield ModelStreamEvent(
                type="error",
                error=str(error_value or "OpenAI Responses stream failed"),
                response_id=response_id,
                raw_event=event,
            )
            return

    if not terminal_seen:
        yield ModelStreamEvent(
            type="error",
            error="OpenAI Responses stream ended before a terminal response event",
            response_id=response_id,
        )
