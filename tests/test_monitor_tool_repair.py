from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from shopagent_monitor.app.agent import MonitoringAgent, TOOL_REPAIR_PROMPT
from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.search_history import SearchRecorder
from shopagent_monitor.app.search_limits import SearchLimits
from shopagent_monitor.app.search_progress import SearchCancelled
from shopagent_monitor.app.service import MonitoringService
from shopagent_monitor.app.store import MonitorStore
from shopagent_monitor.app.web import create_app
from shopagent_monitor.llm.messages import ToolResultMessage
from shopagent_monitor.llm.model import (
    ModelConfig,
    ModelContextBudgetError,
    ModelEventStream,
    ModelResponse,
    ModelResponseError,
    ModelStreamEvent,
    ModelToolCall,
)


def call(name, arguments):
    return ModelResponse(text="", tool_call=ModelToolCall(name, arguments, name))


SEARCH = call("search", {"query": "保温杯"})
INSPECT = call("inspect_product", {"asin": "A"})
FINISH = call("finish", {"candidates": [{"asin": "A", "reason": "公开详情匹配"}]})
NO_TOOL = ModelResponse(text="private failed prose: 不再按工具协议返回")


class ScriptBackend:
    def __init__(self, responses, *, streaming=False):
        self.responses = iter(responses)
        self.contexts = []
        self.config = ModelConfig(
            provider="openai-responses", model="fixture", stream=streaming, api_key_required=False, max_retries=2
        )

    def _response(self, context):
        self.contexts.append(context)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value

    def generate(self, *, context, **kwargs):
        return self._response(context)

    def stream(self, *, context, **kwargs):
        def source():
            response = self._response(context)
            if response.tool_call:
                yield ModelStreamEvent(type="toolcall_end", tool_call=response.tool_call)
            else:
                yield ModelStreamEvent(type="text_delta", text_delta=response.text)
            yield ModelStreamEvent(type="done", response=response)

        return ModelEventStream(source())


class MonitorToolRepairTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dataset = self.root / "items.json"
        self.dataset.write_text(
            json.dumps(
                [
                    {
                        "asin": "A",
                        "title": "保温杯 A",
                        "pricing": [50],
                        "full_description": "公开详情证据",
                        "customization_options": {"颜色": [{"value": "白色"}, {"value": "黑色"}]},
                    },
                    {"asin": "B", "title": "保温杯 B", "pricing": [80], "customization_options": {}},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.catalog = MonitoringCatalog(self.dataset)
        self.store = MonitorStore(self.root / "monitor.sqlite3")

    def agent(self, backend, **kwargs):
        return MonitoringAgent(self.catalog, backend.config, backend=backend, **kwargs)

    def test_missing_tool_repairs_same_stage_with_full_history_for_both_response_modes(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                backend = ScriptBackend([SEARCH, INSPECT, NO_TOOL, FINISH], streaming=streaming)
                events = []
                with (
                    patch.object(self.catalog, "search", wraps=self.catalog.search) as search,
                    patch.object(self.catalog, "product", wraps=self.catalog.product) as product,
                ):
                    result = self.agent(backend).search("保温杯", on_progress=events.append)
                self.assertEqual(result["engine"], "model")
                self.assertTrue(result["selection_complete"])
                self.assertEqual(search.call_count, 1)
                self.assertEqual(sum(c.kwargs.get("detail", False) for c in product.call_args_list), 1)
                before, repaired = backend.contexts[2:]
                self.assertEqual(repaired.messages[:-1], before.messages)
                self.assertEqual(repaired.messages[-1].content, TOOL_REPAIR_PROMPT)
                self.assertEqual(sum(isinstance(m, ToolResultMessage) for m in repaired.messages), 2)
                self.assertIn("公开详情证据", str(repaired.messages))
                self.assertNotIn(NO_TOOL.text, str(repaired.messages))
                self.assertEqual([s["tool"] for s in result["steps"]], ["search", "inspect_product"])
                self.assertEqual(len([e for e in events if e["stage"] == "tool_repair"]), 1)
                self.assertNotIn(NO_TOOL.text, json.dumps(events, ensure_ascii=False))

    def test_two_repairs_total_then_preserve_every_visible_candidate_and_execution_record(self):
        # A valid call between two protocol failures must not reset the repair budget.
        backend = ScriptBackend([SEARCH, NO_TOOL, INSPECT, NO_TOOL, NO_TOOL, FINISH])
        events = []
        with patch.object(self.catalog, "search", wraps=self.catalog.search) as search:
            result = SearchRecorder(self.agent(backend), self.store, "fixture").search(
                "保温杯", on_progress=events.append
            )
        self.assertEqual(len(backend.contexts), 5)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(result["engine"], "partial")
        self.assertFalse(result["selection_complete"])
        self.assertEqual({p["asin"] for p in result["products"]}, {"A", "B"})
        self.assertTrue(all("尚未完成" in p["reason"] for p in result["products"]))
        self.assertEqual([s["tool"] for s in result["steps"]], ["search", "inspect_product"])
        self.assertEqual(len([e for e in events if e["stage"] == "tool_repair"]), 2)
        saved = MonitorStore(self.store.path).get_search(result["search_id"])
        self.assertEqual(saved["engine"], "partial")
        self.assertFalse(saved["selection_complete"])
        self.assertEqual(saved["products"], result["products"])
        self.assertEqual(saved["steps"], result["steps"])
        self.assertFalse(any(e["status"] == "running" for e in saved["events"]))
        self.assertNotIn(NO_TOOL.text, json.dumps(saved, ensure_ascii=False))

    def test_invalid_schema_unknown_tool_and_unseen_finish_id_are_repaired_before_execution(self):
        failures = [
            call("search", {"query": "多余参数", "unknown": 1}),
            call("buy", {"asin": "A"}),
            call("finish", {"candidates": [{"asin": "invented", "reason": "伪造"}]}),
            ModelResponseError("invalid tool JSON"),
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                backend = ScriptBackend([SEARCH, failure, FINISH])
                with patch.object(self.catalog, "search", wraps=self.catalog.search) as search:
                    result = self.agent(backend).search("保温杯")
                self.assertEqual(result["engine"], "model")
                self.assertEqual(search.call_count, 1)
                self.assertEqual([p["asin"] for p in result["products"]], ["A"])
                self.assertEqual(len(backend.contexts[-1].messages), 4)
                self.assertEqual(backend.contexts[-1].messages[-1].content, TOOL_REPAIR_PROMPT)

    def test_repairs_consume_rounds_without_resetting_tool_allowances(self):
        backend = ScriptBackend([SEARCH, NO_TOOL, SEARCH, FINISH])
        events = []
        with patch.object(self.catalog, "search", wraps=self.catalog.search) as search:
            result = self.agent(
                backend, search_limits=SearchLimits(max_searches=1, max_inspections=0, max_model_rounds=4)
            ).search("保温杯", on_progress=events.append)
        self.assertEqual(result["engine"], "model")
        self.assertEqual(search.call_count, 1)
        self.assertIn("剩余搜索 0 次", backend.contexts[2].system_prompt)
        self.assertIn("第 4/4 轮", backend.contexts[-1].system_prompt)
        self.assertTrue(any("搜索次数已达上限" in e["message"] for e in events))

    def test_last_round_does_not_launch_extra_repair(self):
        backend = ScriptBackend([SEARCH, NO_TOOL, FINISH])
        events = []
        result = self.agent(backend, search_limits=SearchLimits(max_model_rounds=2)).search(
            "保温杯", on_progress=events.append
        )
        self.assertEqual(len(backend.contexts), 2)
        self.assertEqual(result["engine"], "partial")
        self.assertFalse(any(e["stage"] == "tool_repair" for e in events))

    def test_no_prior_candidates_falls_back_only_after_bounded_repairs(self):
        backend = ScriptBackend([NO_TOOL] * 4)
        events = []
        with patch.object(self.catalog, "search", wraps=self.catalog.search) as search:
            result = self.agent(backend).search("原始描述保温杯", on_progress=events.append)
        self.assertEqual(len(backend.contexts), 3)
        self.assertEqual(result["engine"], "catalog")
        search.assert_called_once_with("原始描述保温杯")
        self.assertEqual(len([e for e in events if e["stage"] == "tool_repair"]), 2)
        self.assertIn("暂无可保留", result["message"])

    def test_empty_finish_is_completed_screening_without_repair_or_fallback(self):
        backend = ScriptBackend([call("finish", {"candidates": []})])
        with patch.object(self.catalog, "search", wraps=self.catalog.search) as search:
            result = self.agent(backend).search("不存在")
        self.assertEqual(result["engine"], "model")
        self.assertTrue(result["selection_complete"])
        self.assertEqual(result["products"], [])
        search.assert_not_called()

    def test_exhausted_network_retries_keep_candidates_without_protocol_repair(self):
        backend = ScriptBackend([SEARCH] + [TimeoutError("timed out")] * 3 + [FINISH])
        events = []
        with (
            patch("shopagent_monitor.app.model_requests.time.sleep"),
            patch.object(self.catalog, "search", wraps=self.catalog.search) as search,
        ):
            result = self.agent(backend).search("保温杯", on_progress=events.append)
        self.assertEqual(len(backend.contexts), 4)
        self.assertIs(backend.contexts[1], backend.contexts[2])
        self.assertIs(backend.contexts[2], backend.contexts[3])
        self.assertEqual(result["engine"], "partial")
        self.assertEqual(result["model_error"]["kind"], "timeout")
        self.assertEqual(search.call_count, 1)
        self.assertFalse(any(e["stage"] == "tool_repair" for e in events))

    def test_auth_and_context_errors_are_not_protocol_repairs(self):
        failures = [
            HTTPError("http://localhost/v1/responses", 401, "Unauthorized", {}, None),
            ModelContextBudgetError("上下文超过客户端上限"),
        ]
        for failure in failures:
            backend = ScriptBackend([SEARCH, failure, FINISH])
            events = []
            result = self.agent(backend).search("保温杯", on_progress=events.append)
            self.assertEqual(len(backend.contexts), 2)
            self.assertEqual(result["engine"], "partial")
            self.assertFalse(any(e["stage"] == "tool_repair" for e in events))

    def test_cancel_during_protocol_repair_stops_without_another_call_or_history(self):
        backend = ScriptBackend([SEARCH, NO_TOOL, FINISH])
        cancelled = threading.Event()

        def on_progress(event):
            if event["stage"] == "tool_repair":
                cancelled.set()

        with self.assertRaises(SearchCancelled):
            SearchRecorder(self.agent(backend), self.store, "fixture").search(
                "保温杯", on_progress=on_progress, cancelled=cancelled
            )
        self.assertEqual(len(backend.contexts), 2)
        self.assertEqual(self.store.list_searches()["total"], 0)

    def test_json_and_ndjson_preserve_partial_state_and_history_after_reopen(self):
        service = MonitoringService(self.catalog, self.store)
        for endpoint in ("/api/search", "/api/search/stream"):
            backend = ScriptBackend([SEARCH, INSPECT] + [NO_TOOL] * 3)
            with TestClient(
                create_app(service=service, agent=self.agent(backend), model_config=None, scheduler_enabled=False)
            ) as client:
                response = client.post(endpoint, json={"description": "保温杯"})
                self.assertEqual(response.status_code, 200)
                if endpoint.endswith("stream"):
                    events = [json.loads(line) for line in response.text.splitlines()]
                    self.assertEqual(events[-1]["type"], "result")
                    result = events[-1]["result"]
                    self.assertEqual(sum(e.get("stage") == "tool_repair" for e in events), 2)
                else:
                    result = response.json()
                self.assertEqual(result["engine"], "partial")
                self.assertFalse(result["selection_complete"])
                self.assertIn("尚未完成筛选", result["message"])
            reopened = MonitoringService(self.catalog, MonitorStore(self.store.path))
            with TestClient(create_app(service=reopened, model_config=None, scheduler_enabled=False)) as client:
                saved = client.get("/api/search-history/" + result["search_id"]).json()
                self.assertEqual(saved["engine"], "partial")
                self.assertFalse(saved["selection_complete"])
                self.assertEqual(saved["products"], result["products"])
                self.assertEqual(client.get("/api/search-history").json()["records"][0]["engine"], "partial")


if __name__ == "__main__":
    unittest.main()
