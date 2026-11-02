from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest

from shopagent_monitor.app.advice import PurchaseAdvisor
from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.domain import MonitorError, PriceQuote
from shopagent_monitor.app.service import MonitoringService
from shopagent_monitor.app.store import MonitorStore
from shopagent_monitor.llm.model import ModelResponse, ModelToolCall


class AdviceBackend:
    def __init__(self, decision="consider_buying", reasons=None, *, skip_read=False, fail=False):
        self.decision, self.reasons = decision, reasons or ["low", "scope"]
        self.skip_read, self.fail, self.contexts = skip_read, fail, []

    def generate(self, *, context, **_kwargs):
        self.contexts.append(context)
        if self.fail:
            raise RuntimeError("private provider details must not appear")
        call = (
            ModelToolCall("get_monitoring_summary", {}, "read")
            if len(self.contexts) == 1 and not self.skip_read
            else ModelToolCall("finish_advice", {"decision": self.decision, "reason_ids": self.reasons}, "finish")
        )
        return ModelResponse(text="", tool_call=call)


class PurchaseAdviceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "items.json").write_text(
            json.dumps(
                [
                    {
                        "asin": "A",
                        "title": "公开耳机",
                        "pricing": [100],
                        "category": "数码",
                        "customization_options": {},
                        "instructions": [{"instruction": "HIDDEN ANSWER"}],
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.catalog = MonitoringCatalog(self.root / "items.json")
        self.store = MonitorStore(self.root / "monitor.sqlite3")
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        self.service = MonitoringService(self.catalog, self.store, clock=lambda: self.now)
        self.watch = self.service.add("A", {}, request="关注耳机", interval=30)["watch"]

    def tearDown(self):
        self.tmp.cleanup()

    def prices(self, *values):
        for value in values:
            self.now += timedelta(seconds=30)
            self.store.import_quotes([(self.watch["id"], PriceQuote(value, self.now, "import"))], self.now)

    def evidence(self, **prefs):
        return self.service.advice_evidence(self.watch["id"], **prefs)

    def rules(self, **prefs):
        return PurchaseAdvisor().advise(self.evidence(**prefs))

    def test_first_quote_does_not_claim_a_reliable_buying_opportunity(self):
        advice = self.rules()
        self.assertEqual(advice["decision"], "keep_watching")
        self.assertEqual(advice["metrics"]["recent_direction"], "insufficient")
        self.assertFalse(advice["metrics"]["new_low"])
        self.assertIn("limited", [r["id"] for r in advice["reasons"]])

    def test_urgency_can_support_a_purchase_but_keeps_limited_evidence(self):
        advice = self.rules(urgency="soon", budget="100")
        self.assertEqual(advice["decision"], "consider_buying")
        self.assertIn("limited", [r["id"] for r in advice["reasons"]])
        self.assertEqual(self.rules(urgency="soon", budget="90")["decision"], "wait")

    def test_low_price_is_qualified_by_observed_trend_and_user_timing(self):
        self.prices(9500, 9000)
        self.assertEqual(self.rules()["decision"], "keep_watching")
        self.assertEqual(self.rules(urgency="soon")["decision"], "consider_buying")
        self.assertTrue(self.rules()["metrics"]["new_low"])
        self.prices(9000)
        self.assertFalse(self.rules()["metrics"]["new_low"])

    def test_rebound_and_budget_are_computed_from_exact_saved_prices(self):
        self.prices(8000, 9500)
        result = self.rules(budget="90", urgency="soon")
        self.assertEqual(result["decision"], "wait")
        self.assertEqual(result["metrics"]["gap_to_low_percent"], 18.75)
        self.assertEqual(result["metrics"]["low_price"], "80.00")
        self.assertIn("5.00", next(r["text"] for r in result["reasons"] if r["id"] == "budget"))

    def test_error_or_stale_quote_requires_new_evidence_even_at_low_price(self):
        self.prices(9000, 8000)
        token = self.store.claim(self.watch["id"], self.now, force=True)
        self.store.finish_check(self.watch["id"], token, self.now, error="报价失败")
        self.assertEqual(self.rules(urgency="soon")["decision"], "refresh_quote")
        self.prices(8000)
        self.now += timedelta(seconds=91)
        result = self.rules(urgency="soon")
        self.assertEqual(result["decision"], "refresh_quote")
        self.assertTrue(result["metrics"]["quote_stale"])

    def test_recent_window_is_bounded_but_low_and_revision_use_all_history(self):
        self.prices(5000, *([9900] * 14))
        result = self.rules()
        self.assertEqual(result["metrics"]["recent_count"], 12)
        self.assertEqual(result["metrics"]["sample_count"], 16)
        self.assertEqual(result["metrics"]["low_price"], "50.00")
        previous = result["based_on"]["history_revision"]
        self.store.import_quotes(
            [(self.watch["id"], PriceQuote(4000, self.now - timedelta(days=1), "import"))], self.now
        )
        latest = self.rules()
        self.assertGreater(latest["based_on"]["history_revision"], previous)
        self.assertEqual(latest["metrics"]["current_price"], "99.00")
        self.assertEqual(latest["metrics"]["low_price"], "40.00")

    def test_native_agent_reads_facts_and_returns_supported_plan_without_writes(self):
        self.prices(9500, 9000)
        backend = AdviceBackend()
        before = self.store.history(self.watch["id"]), self.store.alerts(), self.store.get(self.watch["id"])
        advice = PurchaseAdvisor(backend).advise(self.evidence(urgency="soon"))
        self.assertEqual(advice["engine"], "model")
        self.assertEqual(advice["decision"], "consider_buying")
        self.assertEqual(len(backend.contexts), 2)
        self.assertIn("90.00", backend.contexts[1].messages[-1].content)
        self.assertEqual(
            before, (self.store.history(self.watch["id"]), self.store.alerts(), self.store.get(self.watch["id"]))
        )
        self.assertIn("current", [r["id"] for r in advice["reasons"]])

    def test_future_replay_scenario_and_private_task_fields_never_reach_model(self):
        self.watch = self.service.add(
            "A",
            {},
            request="耳机",
            mode="simulation",
            interval=30,
            simulation={"engine": "replay", "scenario": "continuous_lows", "tick_seconds": 30},
        )["watch"]
        backend = AdviceBackend("keep_watching", ["scope", "limited"])
        result = PurchaseAdvisor(backend).advise(self.evidence())
        prompt = backend.contexts[-1].messages[-1].content
        for forbidden in (
            "continuous_lows",
            "scenario",
            "tick_seconds",
            "simulation_runs",
            "HIDDEN ANSWER",
            "customization_options",
        ):
            self.assertNotIn(forbidden, prompt)
        self.assertEqual(result["engine"], "model")
        self.assertIn("simulation", [r["id"] for r in result["reasons"]])

    def test_unsupported_model_decision_or_evidence_falls_back(self):
        for backend in (
            AdviceBackend(),
            AdviceBackend("buy_now"),
            AdviceBackend("keep_watching", ["invented"]),
            AdviceBackend("keep_watching", ["error", "scope"]),
            AdviceBackend("keep_watching", skip_read=True),
            AdviceBackend(fail=True),
        ):
            result = PurchaseAdvisor(backend).advise(self.evidence(budget="50"))
            self.assertEqual(result["engine"], "rules")
            self.assertEqual(result["decision"], "wait")
            self.assertNotIn("private", json.dumps(result))

    def test_busy_model_falls_back_and_releases_lock_after_failure(self):
        lock = threading.BoundedSemaphore(1)
        backend = AdviceBackend(fail=True)
        advisor = PurchaseAdvisor(backend, model_lock=lock)
        lock.acquire()
        self.assertEqual(advisor.advise(self.evidence())["engine"], "rules")
        self.assertEqual(backend.contexts, [])
        lock.release()
        advisor.advise(self.evidence())
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()

    def test_invalid_preferences_and_missing_watch_are_rejected(self):
        for budget in (True, 0, -1, "NaN", "1.001", {}, []):
            with self.assertRaises(MonitorError):
                self.evidence(budget=budget)
        with self.assertRaises(MonitorError):
            self.evidence(urgency="invented")
        with self.assertRaises(MonitorError):
            self.service.advice_evidence("missing")

    def test_http_advice_rules_validation_and_native_model(self):
        from fastapi.testclient import TestClient
        from shopagent_monitor.app.agent import MonitoringAgent
        from shopagent_monitor.app.web import create_app

        backend = AdviceBackend("keep_watching", ["scope", "limited"])
        app = create_app(
            service=self.service, agent=MonitoringAgent(self.catalog, backend=backend), scheduler_enabled=False
        )
        with TestClient(app) as client:
            path = f"/api/watches/{self.watch['id']}/advice"
            result = client.post(path, json={"budget": "100", "urgency": "flexible"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["engine"], "model")
            self.assertEqual(client.post(path, json={"budget": True}).status_code, 400)
            self.assertEqual(client.post(path, json={"urgency": "unknown"}).status_code, 422)
            self.assertEqual(client.post("/api/watches/missing/advice", json={}).status_code, 404)
        with TestClient(create_app(service=self.service, model_config=None, scheduler_enabled=False)) as client:
            self.assertEqual(client.post(path, json={}).json()["engine"], "rules")


if __name__ == "__main__":
    unittest.main()
