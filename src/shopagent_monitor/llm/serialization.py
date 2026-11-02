"""Native provider payloads and strict tool-call parsing."""

from __future__ import annotations

import json
from typing import Any, Mapping
from .messages import AgentMessage, AssistantMessage, ToolResultMessage, UserMessage
from .types import ModelToolCall


def _openai_input(messages: tuple[AgentMessage, ...]) -> list[dict[str, Any]]:
    """Convert neutral messages to OpenAI Responses input items."""

    result: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            result.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": message.content}],
                }
            )
        elif isinstance(message, AssistantMessage):
            if message.tool_call_id and message.tool_name:
                result.append(
                    {
                        "type": "function_call",
                        "call_id": message.tool_call_id,
                        "name": message.tool_name,
                        "arguments": json.dumps(dict(message.arguments), ensure_ascii=False),
                    }
                )
            elif message.content:
                result.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": message.content}],
                    }
                )
        elif isinstance(message, ToolResultMessage):
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                }
            )
        elif message.content:
            result.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": f"[context summary]\n{message.content}"}],
                }
            )
    return result


def _openai_tools(
    tools: tuple[Mapping[str, Any], ...],
    *,
    strict: bool = True,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tool in tools:
        definition = {
            "type": "function",
            "name": str(tool["name"]),
            "description": str(tool.get("description", "")),
            "parameters": (
                _strict_parameters(tool.get("input_schema", {})) if strict else dict(tool.get("input_schema", {}))
            ),
        }
        if strict:
            definition["strict"] = True
        result.append(definition)
    return result


def _openai_chat_messages(
    system_prompt: str,
    messages: tuple[AgentMessage, ...],
) -> list[dict[str, Any]]:
    """Convert neutral messages to OpenAI Chat Completions messages."""

    result: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if isinstance(message, UserMessage):
            result.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            if message.tool_call_id and message.tool_name:
                result.append(
                    {
                        "role": "assistant",
                        "content": message.content or None,
                        "tool_calls": [
                            {
                                "id": message.tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": message.tool_name,
                                    "arguments": json.dumps(dict(message.arguments), ensure_ascii=False),
                                },
                            }
                        ],
                    }
                )
            elif message.content:
                result.append({"role": "assistant", "content": message.content})
        elif isinstance(message, ToolResultMessage):
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
        elif message.content:
            result.append({"role": "user", "content": f"[context summary]\n{message.content}"})
    return result


def _openai_chat_tools(tools: tuple[Mapping[str, Any], ...]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": str(tool["name"]),
                "description": str(tool.get("description", "")),
                "parameters": dict(tool.get("input_schema", {})),
            },
        }
        for tool in tools
    ]


def _strict_parameters(schema: Any) -> dict[str, Any]:
    """Normalize a JSON schema for OpenAI strict function calling."""

    if not isinstance(schema, Mapping):
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    result = dict(schema)
    properties = result.get("properties", {})
    if not isinstance(properties, Mapping):
        properties = {}
    result["properties"] = {
        str(key): dict(value) if isinstance(value, Mapping) else value for key, value in properties.items()
    }
    result["required"] = [str(key) for key in properties]
    result["additionalProperties"] = False
    return result


def _gemini_contents(messages: tuple[AgentMessage, ...]) -> list[dict[str, Any]]:
    """Convert neutral messages to Gemini ``contents``."""

    result: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            result.append({"role": "user", "parts": [{"text": message.content}]})
        elif isinstance(message, AssistantMessage):
            if message.tool_call_id and message.tool_name:
                function_call = {
                    "name": message.tool_name,
                    "args": dict(message.arguments),
                }
                part: dict[str, Any] = {"functionCall": function_call}
                if message.thought_signature:
                    part["thoughtSignature"] = message.thought_signature
                result.append(
                    {
                        "role": "model",
                        "parts": [part],
                    }
                )
            elif message.content:
                result.append({"role": "model", "parts": [{"text": message.content}]})
        elif isinstance(message, ToolResultMessage):
            function_response = {
                "functionResponse": {
                    "name": message.tool_name,
                    "response": {"error" if message.is_error else "output": message.content},
                }
            }
            # Gemini requires consecutive function responses in one user turn.
            last_content = result[-1] if result else None
            if (
                isinstance(last_content, dict)
                and last_content.get("role") == "user"
                and isinstance(last_content.get("parts"), list)
                and any(isinstance(part, dict) and "functionResponse" in part for part in last_content["parts"])
            ):
                last_content["parts"].append(function_response)
            else:
                result.append({"role": "user", "parts": [function_response]})
        elif message.content:
            result.append({"role": "user", "parts": [{"text": f"[context summary]\n{message.content}"}]})
    return result


def _gemini_tools(tools: tuple[Mapping[str, Any], ...]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {
                    "name": str(tool["name"]),
                    "description": str(tool.get("description", "")),
                    "parametersJsonSchema": dict(tool.get("input_schema", {})),
                }
                for tool in tools
            ]
        }
    ]


def _parse_tool_arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, Mapping):
        return None
    return dict(value)


def _extract_openai_chat_message(
    value: Mapping[str, Any],
) -> tuple[str, ModelToolCall | None]:
    choices = value.get("choices", [])
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return "", None
    message = choices[0].get("message", {})
    if not isinstance(message, Mapping):
        return "", None
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        )
    else:
        text = ""

    tool_calls = message.get("tool_calls", [])
    if isinstance(tool_calls, list):
        for item in tool_calls:
            if not isinstance(item, Mapping):
                continue
            function = item.get("function", {})
            if not isinstance(function, Mapping):
                continue
            name = function.get("name")
            arguments = _parse_tool_arguments(function.get("arguments", {}))
            if isinstance(name, str) and name.strip() and arguments is not None:
                call_id = item.get("id")
                return text, ModelToolCall(
                    name=name.strip(),
                    arguments=arguments,
                    call_id=str(call_id) if call_id else None,
                )

    # A few older OpenAI-compatible servers still emit the deprecated shape.
    function = message.get("function_call", {})
    if isinstance(function, Mapping):
        name = function.get("name")
        arguments = _parse_tool_arguments(function.get("arguments", {}))
        if isinstance(name, str) and name.strip() and arguments is not None:
            return text, ModelToolCall(name=name.strip(), arguments=arguments)
    return text, None


def _extract_openai_tool_call(value: Mapping[str, Any]) -> ModelToolCall | None:
    output = value.get("output", [])
    if not isinstance(output, list):
        return None
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "function_call":
            continue
        name = item.get("name")
        arguments = _parse_tool_arguments(item.get("arguments", {}))
        if isinstance(name, str) and name.strip() and arguments is not None:
            call_id = item.get("call_id") or item.get("id")
            return ModelToolCall(name=name.strip(), arguments=arguments, call_id=str(call_id) if call_id else None)
    return None


def _extract_gemini_tool_call(value: Mapping[str, Any]) -> ModelToolCall | None:
    candidates = value.get("candidates", [])
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, Mapping):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, Mapping) or not isinstance(part.get("functionCall"), Mapping):
                continue
            function_call = part["functionCall"]
            name = function_call.get("name")
            arguments = _parse_tool_arguments(function_call.get("args", {}))
            if isinstance(name, str) and name.strip() and arguments is not None:
                thought_signature = part.get("thoughtSignature")
                if not isinstance(thought_signature, str) or not thought_signature:
                    thought_signature = None
                return ModelToolCall(
                    name=name.strip(),
                    arguments=arguments,
                    thought_signature=thought_signature,
                )
    return None


def _extract_text(value: Mapping[str, Any]) -> str:
    direct = value.get("output_text")
    if isinstance(direct, str):
        return direct
    output = value.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
                if isinstance(content, Mapping) and isinstance(content.get("text"), str):
                    return content["text"]
    return ""


def _extract_gemini_text(value: Mapping[str, Any]) -> str:
    candidates = value.get("candidates", [])
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, Mapping):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        texts = [str(part["text"]) for part in parts if isinstance(part, Mapping) and isinstance(part.get("text"), str)]
        if texts:
            return "".join(texts)
    return ""


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _gemini_reasoning_budget(effort: str) -> int:
    """Map portable effort names to Gemini's token-based thinking budget."""

    return {
        "minimal": 512,
        "low": 1024,
        "medium": 4096,
        "high": 8192,
        "xhigh": 12288,
        "max": 16384,
        "ultra": 24576,
    }.get(effort, 0)


def _provider_error_detail(body: str) -> str:
    """Extract a short, credential-safe provider error description."""

    value = str(body or "").replace("sk-", "<redacted-key-prefix>")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value[:500]
    if isinstance(parsed, Mapping):
        error = parsed.get("error")
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("detail") or error.get("type")
            if message:
                return str(message)[:500]
    return value[:500]
