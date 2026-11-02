from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from shopagent_monitor.app.agent import MonitoringAgent
from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.domain import MonitorError
from shopagent_monitor.app.search_history import SearchRecorder
from shopagent_monitor.app.search_progress import SearchCancelled, search_events
from shopagent_monitor.app.service import MonitoringService
from shopagent_monitor.app.store import MonitorStore
from shopagent_monitor.llm.model import ModelResponse, ModelToolCall

try:
    from fastapi.testclient import TestClient
    from shopagent_monitor.app.web import create_app
except ImportError:
    TestClient = None


class HistoryFixture:
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dataset = self.root / "items.json"
        self.dataset.write_text(
            json.dumps(
                [
                    {"asin": "A", "title": "无线降噪耳机", "pricing": [80], "customization_options": {}},
                    {"asin": "B", "title": "不锈钢保温杯", "pricing": [49], "customization_options": {}},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.catalog = MonitoringCatalog(self.dataset)
        self.store = MonitorStore(self.root / "monitor.sqlite3")
        self.agent = MonitoringAgent(self.catalog)
        self.recorder = SearchRecorder(self.agent, self.store, "fixture-revision")
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)

    def record(self, description="耳机", result=None):
        result = result or {
            "engine": "model",
            "message": "已完成公开商品筛选",
            "products": [{**self.catalog.product("A"), "reason": "支持无线和降噪"}],
        }
        return self.store.save_search(
            description,
            result,
            events=[],
            started_at=self.now,
            completed_at=self.now,
            elapsed_ms=1200,
            model_revision="fixture-revision",
            search_limits=self.agent.search_limits.model_dump(),
        )


class SearchHistoryTests(HistoryFixture, unittest.TestCase):
    def test_catalog_search_and_zero_candidates_are_recorded(self):
        for description in ("耳机", "完全不存在的商品xyz"):
            with self.subTest(description=description):
                result = self.recorder.search(description)
                saved = self.store.get_search(result["search_id"])
                self.assertEqual(saved["description"], description)
                self.assertEqual(saved["products"], result["products"])
                self.assertEqual(saved["result_count"], len(result["products"]))
                self.assertEqual(saved["engine"], "catalog")
                self.assertEqual(saved["model_revision"], "fixture-revision")
                self.assertEqual(saved["events"][-1]["stage"], "completed")
                self.assertGreaterEqual(saved["elapsed_ms"], 0)
        self.assertEqual(self.store.list_searches()["total"], 2)

    def test_model_reason_survives_without_raw_response_or_answers(self):
        class Backend:
            def __init__(self):
                self.calls = iter(
                    [
                        ("search", {"query": "耳机"}),
                        ("inspect_product", {"asin": "A"}),
                        ("finish", {"candidates": [{"asin": "A", "reason": "公开标题包含无线和降噪"}]}),
                    ]
                )

            def generate(self, **_kwargs):
                name, args = next(self.calls)
                return ModelResponse(text="private-provider-content", tool_call=ModelToolCall(name, args, name))

        result = SearchRecorder(MonitoringAgent(self.catalog, backend=Backend()), self.store, "model-r1").search("耳机")
        saved = self.store.get_search(result["search_id"])
        self.assertEqual(saved["engine"], "model")
        self.assertEqual(saved["products"][0]["reason"], "公开标题包含无线和降噪")
        self.assertNotIn("private-provider-content", json.dumps(saved))
        result["products"][0]["reason"] = "mutated"
        self.assertNotEqual(self.store.get_search(saved["id"])["products"][0]["reason"], "mutated")

    def test_reopen_and_current_catalog_changes_do_not_rewrite_snapshot(self):
        search_id = self.record()
        self.dataset.write_text('[{"asin":"A","title":"新的标题","pricing":[99]}]', encoding="utf-8")
        current = MonitoringCatalog(self.dataset).product("A")
        saved = MonitorStore(self.store.path).get_search(search_id)
        self.assertEqual(current["price"], 99)
        self.assertEqual(saved["products"][0]["price"], 80)
        self.assertEqual(saved["products"][0]["title"], "无线降噪耳机")
        self.assertNotIn("snapshot", saved)

    def test_only_whitelisted_public_fields_are_persisted(self):
        result = {
            "engine": "model",
            "message": "公开结果",
            "credentials": "fixture-secret",
            "raw_response": "private-response",
            "hidden_goal": "secret-goal",
            "products": [
                {
                    **self.catalog.product("A"),
                    "reason": "公开证据",
                    "target_options": {"hidden": "secret"},
                    "is_selected": True,
                    "provider_response": "private-provider",
                }
            ],
        }
        search_id = self.record(result=result)
        saved = json.dumps(self.store.get_search(search_id))
        for private in (
            "fixture-secret",
            "private-response",
            "secret-goal",
            "target_options",
            "is_selected",
            "private-provider",
        ):
            self.assertNotIn(private, saved)

    def test_cursor_paging_and_literal_keyword_filter(self):
        ids = [self.record(description) for description in ("杯子", "耳机100%", "耳机100_", "耳机100%", "耳机")]
        first = self.store.list_searches(limit=2)
        second = self.store.list_searches(limit=2, before=first["next_cursor"])
        third = self.store.list_searches(limit=2, before=second["next_cursor"])
        self.assertEqual([r["id"] for p in (first, second, third) for r in p["records"]], list(reversed(ids)))
        self.assertEqual([p["total"] for p in (first, second, third)], [5, 5, 5])
        self.assertIsNone(third["next_cursor"])
        self.assertEqual(self.store.list_searches(query="100%")["total"], 2)
        self.assertEqual(self.store.list_searches(query="100_")["total"], 1)
        self.assertEqual(self.store.list_searches(query="' OR 1=1 --")["total"], 0)
        self.assertNotIn("products", first["records"][0])

    def test_concurrent_repeated_requests_have_distinct_complete_snapshots(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.recorder.search, ["耳机", "杯子", "耳机", "杯子"] * 3))
        self.assertEqual(len({r["search_id"] for r in results}), 12)
        self.assertEqual(self.store.list_searches()["total"], 12)
        for result in results:
            self.assertEqual(self.store.get_search(result["search_id"])["products"], result["products"])

    def test_saving_failure_returns_candidates_with_safe_warning(self):
        with patch.object(self.store, "save_search", side_effect=sqlite3.OperationalError("fixture-private-error")):
            with self.assertLogs("shopagent_monitor.app.search_history", level="WARNING") as logs:
                result = self.recorder.search("耳机")
        self.assertTrue(result["products"])
        self.assertIn("未能保存", result["history_warning"])
        self.assertNotIn("search_id", result)
        self.assertNotIn("fixture-private-error", json.dumps(result) + str(logs.output))
        self.assertEqual(self.store.list_searches()["total"], 0)

    def test_cancelled_or_failed_search_does_not_create_completed_record(self):
        cancel = threading.Event()

        def late_cancel(*_args, **_kwargs):
            cancel.set()
            return {"engine": "catalog", "message": "done", "products": []}

        with patch.object(self.agent, "search", side_effect=late_cancel):
            with self.assertRaises(SearchCancelled):
                self.recorder.search("耳机", cancelled=cancel)
        with patch.object(self.agent, "search", side_effect=RuntimeError("unfinished")):
            with self.assertRaises(RuntimeError):
                self.recorder.search("耳机")
        self.assertEqual(self.store.list_searches()["total"], 0)

    def test_fallback_marks_incomplete_model_steps_interrupted(self):
        def search(_description, *, on_progress, **_kwargs):
            for event in (
                {"step_id": "model1", "stage": "planning", "status": "running", "message": "等待模型", "elapsed_ms": 0},
                {
                    "step_id": "fallback",
                    "stage": "fallback",
                    "status": "notice",
                    "message": "目录回退",
                    "elapsed_ms": 12,
                },
            ):
                on_progress(event)
            return {"engine": "catalog", "message": "目录结果", "products": []}

        with patch.object(self.agent, "search", side_effect=search):
            result = self.recorder.search("耳机")
        saved = self.store.get_search(result["search_id"])
        self.assertEqual(saved["events"][0]["status"], "interrupted")

    def test_monitor_creation_and_schema_upgrade_preserve_search_and_price_history(self):
        service = MonitoringService(self.catalog, self.store, clock=lambda: self.now)
        watch = service.add("A", {}, request="原来的需求", mode="snapshot", interval=30)["watch"]
        before = self.store.stats()
        # Emulate the prior application schema with user monitoring data in place.
        with self.store.transaction() as db:
            db.execute("DROP TABLE search_history")
        self.store = MonitorStore(self.store.path)
        self.assertEqual(self.store.stats(), before)
        search_id = self.record("耳机需求")
        saved = self.store.get_search(search_id)
        added = service.add(
            saved["products"][0]["asin"], {}, request=saved["description"], mode="simulation", interval=30
        )
        self.assertNotEqual(added["watch"]["id"], watch["id"])
        self.assertEqual(added["watch"]["request"], "耳机需求")
        self.assertEqual(self.store.get_search(search_id), saved)

    def test_missing_records_and_invalid_cursors_are_explicit_errors(self):
        with self.assertRaises(MonitorError) as caught:
            self.store.get_search("not-found")
        self.assertEqual(caught.exception.status, 404)
        for options in ({"limit": 0}, {"limit": 101}, {"limit": True}, {"before": 0}, {"before": "x"}):
            with self.subTest(options=options), self.assertRaises(MonitorError):
                self.store.list_searches(**options)


class SearchHistoryStreamTests(HistoryFixture, unittest.IsolatedAsyncioTestCase):
    async def test_result_is_saved_before_stream_terminal_event(self):
        events = [event async for event in search_events(self.recorder, "耳机")]
        self.assertEqual(events[-1]["type"], "result")
        saved = self.store.get_search(events[-1]["result"]["search_id"])
        self.assertEqual(saved["products"], events[-1]["result"]["products"])
        self.assertEqual(saved["events"][-1]["stage"], "completed")


@unittest.skipIf(TestClient is None, "install web extra for HTTP integration tests")
class SearchHistoryHTTPTests(HistoryFixture, unittest.TestCase):
    def test_history_api_persistence_pagination_and_validation(self):
        service = MonitoringService(self.catalog, self.store)
        with TestClient(create_app(service=service, model_config=None, scheduler_enabled=False)) as client:
            ids = [
                client.post("/api/search", json={"description": s}).json()["search_id"]
                for s in ("耳机", "杯子", "耳机")
            ]
            page = client.get("/api/search-history?limit=1&q=耳机").json()
            self.assertEqual(page["total"], 2)
            self.assertEqual(page["records"][0]["id"], ids[-1])
            next_page = client.get(f"/api/search-history?limit=1&q=耳机&before={page['next_cursor']}").json()
            self.assertEqual(next_page["records"][0]["id"], ids[0])
            for path in ("?limit=0", "?limit=101", "?before=0", "?before=abc"):
                self.assertEqual(client.get("/api/search-history" + path).status_code, 422)
            self.assertEqual(client.get("/api/search-history/missing").status_code, 404)
        reopened = MonitoringService(self.catalog, MonitorStore(self.store.path))
        with TestClient(create_app(service=reopened, model_config=None, scheduler_enabled=False)) as client:
            saved = client.get("/api/search-history/" + ids[0]).json()
            self.assertEqual(saved["description"], "耳机")
            self.assertTrue(saved["products"])


if __name__ == "__main__":
    unittest.main()
