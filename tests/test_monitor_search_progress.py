from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from shopagent_monitor.app.agent import MonitoringAgent
from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.search_progress import search_events
from shopagent_monitor.app.service import MonitoringService
from shopagent_monitor.app.store import MonitorStore
from shopagent_monitor.llm.model import ModelFailure, ModelResponse, ModelToolCall

try:
    from fastapi.testclient import TestClient
    from shopagent_monitor.app.web import create_app
except ImportError:
    TestClient = None


def response(name, arguments):
    return ModelResponse(text="private-model-content", tool_call=ModelToolCall(name, arguments, name))


def successful_calls():
    return [
        response("search", {"query": "降噪耳机"}),
        response("inspect_product", {"asin": "A"}),
        response("finish", {"candidates": [{"asin": "A", "reason": "已查看公开商品信息"}]}),
    ]


class Backend:
    def __init__(self, calls=None, *, gate=None):
        self.responses = iter(successful_calls() if calls is None else calls)
        self.gate = gate
        self.entered = threading.Event()
        self.calls = 0

    def generate(self, **_kwargs):
        self.calls += 1
        self.entered.set()
        if self.gate is not None and not self.gate.wait(5):
            raise TimeoutError("test gate timed out")
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class Fixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dataset = self.root / "items.json"
        dataset.write_text(
            json.dumps(
                [
                    {
                        "asin": "A",
                        "title": "黑色降噪耳机",
                        "pricing": [50],
                        "customization_options": {"颜色": ["黑色", "白色"]},
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.catalog = MonitoringCatalog(dataset)


class SearchProgressTests(Fixture, unittest.TestCase):
    def test_public_steps_arrive_in_order_without_changing_search_result(self):
        expected = MonitoringAgent(self.catalog, backend=Backend()).search("降噪耳机")
        events = []
        result = MonitoringAgent(self.catalog, backend=Backend()).search("降噪耳机", on_progress=events.append)
        self.assertEqual(result, expected)
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[0]["stage"], "starting")
        self.assertEqual(events[-1]["stage"], "completed")
        for stage in ("planning", "searching", "inspecting", "summarizing"):
            self.assertIn(stage, [e["stage"] for e in events])
        self.assertNotIn("private-model-content", json.dumps(events))
        self.assertTrue(all(events[i]["elapsed_ms"] <= events[i + 1]["elapsed_ms"] for i in range(len(events) - 1)))

    def test_rejected_tools_are_reported_and_do_not_count_as_finished_inspections(self):
        calls = [
            response("inspect_product", {"asin": "unknown"}),
            *successful_calls()[:2],
            response("search", {"query": "耳机"}),
            response("search", {"query": "黑色"}),
            successful_calls()[-1],
        ]
        events = []
        result = MonitoringAgent(self.catalog, backend=Backend(calls)).search("耳机", on_progress=events.append)
        self.assertEqual(result["engine"], "model")
        self.assertEqual(len([s for s in result["steps"] if s["tool"] == "search"]), 2)
        self.assertEqual(len([e for e in events if e["status"] == "blocked"]), 2)
        self.assertEqual(len([e for e in events if e["stage"] == "inspecting" and e["status"] == "completed"]), 1)

    def test_busy_disabled_and_failed_model_fallbacks_are_explicit_and_redacted(self):
        for kind in ("disabled", "busy", "failed"):
            with self.subTest(kind=kind):
                backend = None if kind == "disabled" else Backend([ModelFailure("Bearer fixture-secret-provider")])
                agent = MonitoringAgent(self.catalog, backend=backend)
                if kind == "busy":
                    agent._model_lock.acquire()
                try:
                    events = []
                    result = agent.search("耳机", on_progress=events.append)
                finally:
                    if kind == "busy":
                        agent._model_lock.release()
                self.assertEqual(result["engine"], "catalog")
                self.assertIn("fallback", [e["stage"] for e in events])
                self.assertEqual(events[-1]["engine"], "catalog")
                self.assertNotIn("fixture-secret", json.dumps(events))

    def test_broken_progress_callback_does_not_trigger_catalog_fallback(self):
        def broken(_event):
            raise ValueError("display failed")

        result = MonitoringAgent(self.catalog, backend=Backend()).search("耳机", on_progress=broken)
        self.assertEqual(result["engine"], "model")


class SearchStreamTests(Fixture, unittest.IsolatedAsyncioTestCase):
    async def test_first_event_is_available_while_model_is_still_waiting(self):
        gate = threading.Event()
        backend = Backend(gate=gate)
        events = search_events(MonitoringAgent(self.catalog, backend=backend), "耳机")
        try:
            first = await asyncio.wait_for(anext(events), 1)
            self.assertEqual(first["stage"], "starting")
            self.assertTrue(await asyncio.to_thread(backend.entered.wait, 1))
            self.assertFalse(gate.is_set())
            gate.set()
            remaining = [event async for event in events]
            self.assertEqual(remaining[-1]["type"], "result")
            self.assertEqual(remaining[-1]["result"]["engine"], "model")
            self.assertEqual(sum(e["type"] == "result" for e in remaining), 1)
            self.assertNotIn("private-model-content", json.dumps([first, *remaining]))
        finally:
            gate.set()
            await events.aclose()

    async def test_disconnect_stops_next_operation_and_keeps_lock_until_inflight_request_returns(self):
        gate = threading.Event()
        backend = Backend(gate=gate)
        agent = MonitoringAgent(self.catalog, backend=backend)
        events = search_events(agent, "耳机")
        try:
            await asyncio.wait_for(anext(events), 1)
            self.assertTrue(await asyncio.to_thread(backend.entered.wait, 1))
            await events.aclose()
            self.assertFalse(agent._model_lock.acquire(blocking=False))
            with patch.object(self.catalog, "search", wraps=self.catalog.search) as search:
                gate.set()
                acquired = False
                for _ in range(100):
                    acquired = agent._model_lock.acquire(blocking=False)
                    if acquired:
                        agent._model_lock.release()
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(acquired)
                search.assert_not_called()
            self.assertEqual(backend.calls, 1)
        finally:
            gate.set()
            await events.aclose()

    async def test_unexpected_stream_failure_has_one_safe_terminal_event(self):
        class Broken:
            def search(self, *_args, **_kwargs):
                raise RuntimeError("Bearer fixture-private-key")

        events = [e async for e in search_events(Broken(), "耳机")]
        self.assertEqual([e["type"] for e in events], ["error"])
        self.assertNotIn("fixture-private-key", json.dumps(events))

    async def test_concurrent_streams_have_independent_event_sequences(self):
        agent = MonitoringAgent(self.catalog)

        async def collect(description):
            return [event async for event in search_events(agent, description)]

        first, second = await asyncio.gather(collect("耳机"), collect("不存在的物品"))
        self.assertEqual(first[0]["sequence"], 1)
        self.assertEqual(second[0]["sequence"], 1)
        self.assertEqual(first[-1]["type"], "result")
        self.assertEqual(second[-1]["type"], "result")
        self.assertIsNot(first[-1]["result"], second[-1]["result"])


@unittest.skipIf(TestClient is None, "install the web extra to run HTTP integration tests")
class SearchStreamHTTPTests(Fixture, unittest.TestCase):
    def test_stream_http_contract_validation_and_original_json_endpoint(self):
        service = MonitoringService(self.catalog, MonitorStore(self.root / "monitor.sqlite3"))
        app = create_app(service=service, model_config=None, scheduler_enabled=False)
        with TestClient(app) as client:
            body = {"description": "耳机"}
            original = client.post("/api/search", json=body).json()
            response = client.post("/api/search/stream", json=body)
            self.assertEqual(response.status_code, 200)
            self.assertIn("application/x-ndjson", response.headers["content-type"])
            self.assertEqual(response.headers["cache-control"], "no-store")
            events = [json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(events[0]["type"], "progress")
            self.assertEqual(events[-1]["type"], "result")
            streamed = events[-1]["result"]
            self.assertNotEqual(streamed["search_id"], original["search_id"])
            self.assertEqual(
                {k: v for k, v in streamed.items() if k != "search_id"},
                {k: v for k, v in original.items() if k != "search_id"},
            )
            for result in (original, streamed):
                saved = client.get(f"/api/search-history/{result['search_id']}")
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(saved.json()["products"], result["products"])
            self.assertEqual(client.post("/api/search/stream", json={"description": "   "}).status_code, 400)
            self.assertEqual(
                client.post("/api/search/stream", json=body, headers={"Origin": "https://evil.invalid"}).status_code,
                403,
            )


if __name__ == "__main__":
    unittest.main()
