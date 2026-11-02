"""Immutable, provider-neutral conversation messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, TypeAlias


@dataclass(frozen=True)
class UserMessage:
    role: Literal["user"]
    content: str
    timestamp: float = 0.0
    kind: str = "user"


@dataclass(frozen=True)
class AssistantMessage:
    role: Literal["assistant"]
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    response_id: str | None = None
    # Gemini returns an encrypted thought signature on some model parts. It
    # must be replayed with the matching function call in the next turn.
    thought_signature: str | None = None
    timestamp: float = 0.0
    kind: str = "assistant"


@dataclass(frozen=True)
class ToolResultMessage:
    role: Literal["tool_result"]
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    timestamp: float = 0.0
    kind: str = "tool_result"


@dataclass(frozen=True)
class CompactionSummaryMessage:
    role: Literal["compaction_summary"]
    content: str
    tokens_before: int = 0
    timestamp: float = 0.0
    kind: str = "compaction_summary"


AgentMessage: TypeAlias = UserMessage | AssistantMessage | ToolResultMessage | CompactionSummaryMessage


@dataclass(frozen=True)
class ModelContext:
    """A provider-neutral model request.

    ``system_prompt`` is intentionally separate from ``messages``.  This is
    the same boundary used by pi: providers may encode it as instructions,
    systemInstruction, or another native field without changing the agent.
    """

    system_prompt: str
    messages: tuple[AgentMessage, ...] = ()
    tools: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "messages": [message_dict(message) for message in self.messages],
            "tools": [dict(tool) for tool in self.tools],
        }


def message_dict(message: AgentMessage) -> dict[str, Any]:
    """Return a JSON-safe, provider-neutral representation of a message."""

    if isinstance(message, UserMessage):
        return {
            "role": message.role,
            "content": message.content,
            "timestamp": message.timestamp,
            "kind": message.kind,
        }
    if isinstance(message, AssistantMessage):
        return {
            "role": message.role,
            "content": message.content,
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "arguments": dict(message.arguments),
            "response_id": message.response_id,
            "thought_signature": message.thought_signature,
            "timestamp": message.timestamp,
            "kind": message.kind,
        }
    if isinstance(message, ToolResultMessage):
        return {
            "role": message.role,
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "content": message.content,
            "is_error": message.is_error,
            "timestamp": message.timestamp,
            "kind": message.kind,
        }
    return {
        "role": message.role,
        "content": message.content,
        "tokens_before": message.tokens_before,
        "timestamp": message.timestamp,
        "kind": message.kind,
    }
