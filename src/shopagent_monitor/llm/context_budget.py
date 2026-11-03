"""Conservative request accounting; no silent trimming of conversation history."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Mapping, Sequence

from .messages import AgentMessage, AssistantMessage, ModelContext

CONTEXT_BUDGET_VERSION = "unicode-context-budget/2"


@dataclass
class ContextTokenCounter:
    scale: float = 1.0

    @staticmethod
    def _text(text: str) -> int:
        ascii_chars = sum(ord(char) < 128 for char in text)
        non_ascii_bytes = len(text.encode("utf-8")) - ascii_chars
        return math.ceil(ascii_chars / 3) + math.ceil(non_ascii_bytes / 2)

    def text(self, text: str) -> int:
        return math.ceil(self._text(text) * self.scale)

    def history(self, messages: Sequence[AgentMessage]) -> int:
        total = 0
        for message in messages:
            content = message.content
            if isinstance(message, AssistantMessage):
                content += message.tool_name or ""
                content += json.dumps(dict(message.arguments), ensure_ascii=False)
            content += getattr(message, "tool_call_id", "") or ""
            total += self._text(content) + 16
        return math.ceil(total * self.scale)

    def tools(self, tools: Sequence[Mapping[str, Any]]) -> int:
        return math.ceil((self._text(json.dumps(list(tools), ensure_ascii=False)) + 16 * len(tools)) * self.scale)

    def fixed(self, context: ModelContext) -> int:
        return self.text(context.system_prompt) + self.tools(context.tools) + math.ceil(128 * self.scale)

    def context(self, context: ModelContext) -> int:
        return self.fixed(context) + self.history(context.messages)

    def observe(self, *, actual_tokens: int, estimated_tokens: int) -> None:
        if actual_tokens > estimated_tokens > 0:
            self.scale *= actual_tokens / estimated_tokens * 1.10

    def telemetry(self) -> dict[str, Any]:
        return {
            "version": CONTEXT_BUDGET_VERSION,
            "counter": "unicode-conservative-estimate",
            "exact_tokenizer": False,
            "calibration_scope": "episode",
            "scale": round(self.scale, 6),
        }
