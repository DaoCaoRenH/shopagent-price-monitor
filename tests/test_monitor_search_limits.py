from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from shopagent_monitor.app.agent import MonitoringAgent
from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.model_settings import ModelSettings, ModelSettingsInput
from shopagent_monitor.app.search_limits import SearchLimits
from shopagent_monitor.llm.model import ModelResponse, ModelToolCall

try:
    from fastapi.testclient import TestClient
    from shopagent_monitor.app.web import create_app
except ImportError:
    TestClient = None


def call(name, arguments):
    return ModelResponse(text="", tool_call=ModelToolCall(name, arguments, name))


SEARCH = call("search", {"query": "保温杯"})
INSPECT = call("inspect_product", {"asin": "A"})
FINISH = call("finish", {"candidates": [{"asin": "A", "reason": "公开商品信息"}]})


class ScriptBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []

    def generate(self, *, context, **_kwargs):
        self.contexts.append(context)
        return next(self.responses)


class MonitorSearchLimitsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dataset = self.root / "items.json"
        dataset.write_text(
            json.dumps([{"asin": "A", "title": "保温杯", "pricing": [50], "customization_options": {}}]),
            encoding="utf-8",
        )
        self.catalog = MonitoringCatalog(dataset)

    def test_validation_accepts_zero_inspections_and_rejects_invalid_limits(self):
        self.assertEqual(SearchLimits(max_inspections=0).max_inspections, 0)
        for changes in (
            {"max_searches": 0},
            {"max_searches": 21},
            {"max_inspections": -1},
            {"max_inspections": 31},
            {"max_model_rounds": 1},
            {"max_model_rounds": 51},
            {"max_model_rounds": True},
            {"max_searches": "3"},
            {"unknown": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SearchLimits(**changes)
        limits = SearchLimits()
        with self.assertRaises(ValueError):
            limits.max_searches = 10

    def test_custom_budget_executes_more_than_the_old_seven_round_limit(self):
        backend = ScriptBackend([SEARCH] * 3 + [INSPECT] * 4 + [FINISH])
        agent = MonitoringAgent(
            self.catalog,
            backend=backend,
            search_limits=SearchLimits(max_searches=3, max_inspections=4, max_model_rounds=10),
        )
        result = agent.search("保温杯")
        self.assertEqual(result["engine"], "model")
        self.assertEqual(len(backend.contexts), 8)
        self.assertEqual([s["tool"] for s in result["steps"]].count("search"), 3)
        self.assertEqual([s["tool"] for s in result["steps"]].count("inspect_product"), 4)
        self.assertIn("最多搜索 3 次、查看商品 4 次", backend.contexts[0].system_prompt)
        self.assertIn("剩余搜索 0 次，剩余商品查看 0 次", backend.contexts[-1].system_prompt)

    def test_rejected_calls_do_not_consume_tool_budget_but_use_model_rounds(self):
        backend = ScriptBackend(
            [call("inspect_product", {"asin": "unknown"}), SEARCH, SEARCH, INSPECT, INSPECT, FINISH]
        )
        events = []
        result = MonitoringAgent(
            self.catalog,
            backend=backend,
            search_limits=SearchLimits(max_searches=1, max_inspections=1, max_model_rounds=6),
        ).search("保温杯", on_progress=events.append)
        self.assertEqual(result["engine"], "model")
        self.assertEqual([s["tool"] for s in result["steps"]], ["search", "inspect_product"])
        blocked = [e["message"] for e in events if e["status"] == "blocked"]
        self.assertEqual(len(blocked), 3)
        self.assertTrue(any("搜索次数已达上限（1/1）" in message for message in blocked))
        self.assertTrue(any("商品查看次数已达上限（1/1）" in message for message in blocked))
        self.assertIn("剩余商品查看 1 次", backend.contexts[1].system_prompt)
        self.assertIn("这是最后一轮", backend.contexts[-1].system_prompt)

    def test_zero_inspections_is_enforced_and_still_allows_finish(self):
        events = []
        result = MonitoringAgent(
            self.catalog,
            backend=ScriptBackend([SEARCH, INSPECT, FINISH]),
            search_limits=SearchLimits(max_inspections=0, max_model_rounds=3),
        ).search("保温杯", on_progress=events.append)
        self.assertEqual(result["engine"], "model")
        self.assertEqual([s["tool"] for s in result["steps"]], ["search"])
        self.assertTrue(any("商品查看次数已达上限（0/0）" in e["message"] for e in events))

    def test_model_round_cap_includes_blocked_attempts_and_reports_limit(self):
        backend = ScriptBackend([SEARCH] * 8)
        events = []
        result = MonitoringAgent(
            self.catalog, backend=backend, search_limits=SearchLimits(max_searches=1, max_model_rounds=3)
        ).search("保温杯", on_progress=events.append)
        self.assertEqual(len(backend.contexts), 3)
        self.assertEqual(result["engine"], "partial")
        self.assertIn("3 轮模型调用上限", result["message"])
        self.assertEqual(len([e for e in events if e["status"] == "blocked"]), 2)
        self.assertTrue(all(e["round_limit"] == 3 for e in events if e["stage"] == "planning"))

    def test_hot_swap_restart_disabled_and_legacy_configs_preserve_limits(self):
        path = self.root / "settings.json"
        initial = MonitoringAgent(self.catalog)
        settings = ModelSettings(initial, path=path)
        body = ModelSettingsInput(
            model="fixture",
            base_url="http://127.0.0.1:8080/v1",
            search_limits=SearchLimits(max_searches=4, max_inspections=6, max_model_rounds=12),
        )
        saved = settings.save(body)
        self.assertEqual(saved["search_limits"], body.search_limits.model_dump())
        self.assertEqual(initial.search_limits, SearchLimits())
        self.assertIs(settings.agent._model_lock, initial._model_lock)
        for disabled in (False, True):
            restored = ModelSettings(MonitoringAgent(self.catalog), path=path, start_disabled=disabled)
            self.assertEqual(restored.agent.search_limits, body.search_limits)
            self.assertEqual(restored.public()["search_limits"], saved["search_limits"])
            self.assertIsNone(restored.load_error)
        settings.save(body.model_copy(update={"enabled": False}))
        self.assertEqual(
            ModelSettings(MonitoringAgent(self.catalog), path=path).agent.search_limits, body.search_limits
        )
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("search_limits")
        path.write_text(json.dumps(raw), encoding="utf-8")
        legacy = ModelSettings(MonitoringAgent(self.catalog), path=path)
        self.assertIsNone(legacy.load_error)
        self.assertEqual(legacy.agent.search_limits, SearchLimits())

    @unittest.skipIf(TestClient is None, "install web extra for HTTP tests")
    def test_http_saves_validated_budgets_without_echoing_invalid_input(self):
        app = create_app(
            dataset=self.root / "items.json",
            db_path=self.root / "monitor.sqlite3",
            model_config=None,
            model_settings_path=self.root / "model.json",
            scheduler_enabled=False,
        )
        with TestClient(app) as client:
            body = {
                "model": "fixture",
                "base_url": "http://127.0.0.1:8080/v1",
                "search_limits": {"max_searches": 3, "max_inspections": 5, "max_model_rounds": 11},
            }
            self.assertEqual(client.put("/api/model-settings", json=body).status_code, 200)
            self.assertEqual(client.get("/api/model-settings").json()["search_limits"], body["search_limits"])
            self.assertEqual(app.state.models.agent.search_limits.max_model_rounds, 11)
            invalid = client.put(
                "/api/model-settings",
                json=body | {"api_key": "fixture-secret", "search_limits": {"max_model_rounds": True}},
            )
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn("fixture-secret", invalid.text)
            self.assertEqual(app.state.models.agent.search_limits.max_model_rounds, 11)


if __name__ == "__main__":
    unittest.main()
