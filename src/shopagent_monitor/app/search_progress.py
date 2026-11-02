"""Public search events and a request-scoped streaming bridge."""

from __future__ import annotations

import asyncio
from contextlib import aclosing, suppress
import threading
import time
from typing import Any, AsyncIterator, Callable


class SearchCancelled(Exception):
    """Stop between operations after the client disconnects."""


class SearchProgress:
    def __init__(
        self, callback: Callable[[dict[str, Any]], None] | None = None, cancelled: threading.Event | None = None
    ):
        self.callback, self.cancelled = callback, cancelled
        self.started = time.monotonic()
        self.sequence = 0

    def emit(self, stage: str, message: str, *, step_id: str, status: str = "running", **details) -> None:
        if self.cancelled is not None and self.cancelled.is_set():
            raise SearchCancelled()
        self.sequence += 1
        if self.callback is not None:
            event = {
                "type": "progress",
                "sequence": self.sequence,
                "stage": stage,
                "step_id": step_id,
                "status": status,
                "message": message,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                **details,
            }
            try:
                self.callback(event)
            except SearchCancelled:
                raise
            except Exception:
                # A display failure must not change the shopping decision.
                pass

    def model_callback(self, step_id: str, **details) -> Callable[[dict[str, Any]], None]:
        last_phase, last_sent = "", 0.0

        def report(event):
            nonlocal last_phase, last_sent
            phase, now = event["phase"], time.monotonic()
            if phase != "retry" and phase == last_phase and now - last_sent < 0.4:
                return
            last_phase, last_sent = phase, now
            labels = {
                "connected": "模型已响应，正在接收数据",
                "generating": "模型正在生成，已收到流式数据",
                "receiving": "正在接收模型回复",
                "tool_arguments": "正在接收工具调用参数",
                "tool_received": "工具参数接收完成，等待整轮响应结束",
                "validating": "响应接收完成，正在校验工具调用",
            }
            if phase == "retry":
                cause = "连接超时" if event["reason"] == "timeout" else "临时连接或服务错误"
                message = (
                    f"{cause}，{event['delay_sec']} 秒后重试 {event['attempt']}/{event['retry_limit']}；"
                    "保留当前轮上下文与已有结果"
                )
            else:
                message = labels.get(phase, "正在接收模型响应")
                if event.get("received_chars"):
                    message += f"（已接收 {event['received_chars']} 字符）"
            if phase == "retry":
                self.emit(
                    "model_retry", message, step_id=f"{step_id}-retry-{event['attempt']}", status="notice", **details
                )
            else:
                self.emit("model_stream", message, step_id=step_id, **details)

        return report


async def search_events(agent: Any, description: str) -> AsyncIterator[dict[str, Any]]:
    """Yield progress before the model finishes, followed by exactly one terminal event."""
    async with aclosing(
        operation_events(lambda publish, cancelled: agent.search(description, on_progress=publish, cancelled=cancelled))
    ) as events:
        async for event in events:
            yield event


async def operation_events(
    operation: Callable, *, error_message: str = "搜索未能完成，请稍后重试。"
) -> AsyncIterator[dict[str, Any]]:
    """Bridge a synchronous read-only operation to a bounded NDJSON stream."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
    cancelled = threading.Event()

    def deliver(event: dict[str, Any]) -> None:
        if not cancelled.is_set() and not queue.full():
            queue.put_nowait(event)

    def publish(event: dict[str, Any]) -> None:
        if cancelled.is_set():
            raise SearchCancelled()
        loop.call_soon_threadsafe(deliver, event)

    async def run() -> None:
        try:
            result = await asyncio.to_thread(operation, publish, cancelled)
            await queue.put({"type": "result", "result": result})
        except SearchCancelled:
            pass
        except Exception:
            # Provider errors may contain credentials; the progress stream never exposes them.
            await queue.put({"type": "error", "message": error_message})

    worker = asyncio.create_task(run())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat"}
                continue
            yield event
            if event["type"] in {"result", "error"}:
                break
    finally:
        cancelled.set()
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        # Cancellation is checked on the next model event or socket timeout. The
        # worker retains the semaphore until the in-flight request is closed.
