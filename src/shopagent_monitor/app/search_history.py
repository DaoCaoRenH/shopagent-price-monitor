"""Record completed public searches before delivering their final result."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from .agent import MonitoringAgent
from .domain import utc_now
from .search_progress import SearchCancelled
from .store import MonitorStore


LOGGER = logging.getLogger(__name__)


class SearchRecorder:
    def __init__(self, agent: MonitoringAgent, store: MonitorStore, model_revision: str):
        self.agent, self.store, self.model_revision = agent, store, model_revision

    def search(
        self,
        description: str,
        *,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        cancelled: threading.Event | None = None,
    ) -> dict[str, Any]:
        started_at, started = utc_now(), time.monotonic()
        steps: dict[str, dict] = {}

        def progress(event):
            if event["stage"] in {"fallback", "retaining"}:
                for step in steps.values():
                    if step["status"] == "running":
                        step["status"] = "interrupted"
            steps[event["step_id"]] = dict(event)
            if on_progress is not None:
                on_progress(event)

        result = self.agent.search(description, on_progress=progress, cancelled=cancelled)
        if cancelled is not None and cancelled.is_set():
            raise SearchCancelled()
        try:
            search_id = self.store.save_search(
                description,
                result,
                events=list(steps.values()),
                started_at=started_at,
                completed_at=utc_now(),
                elapsed_ms=round((time.monotonic() - started) * 1000),
                model_revision=self.model_revision,
                search_limits=self.agent.search_limits.model_dump(),
            )
        except Exception as exc:
            LOGGER.warning("search history save failed: %s", type(exc).__name__)
            return {**result, "history_warning": "候选已返回，但本次搜索记录未能保存。请保留当前页面，稍后重新搜索。"}
        return {**result, "search_id": search_id}
