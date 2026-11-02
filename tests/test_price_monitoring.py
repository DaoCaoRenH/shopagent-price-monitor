from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest

from shopagent_monitor.app.agent import MonitoringAgent
from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.domain import MonitorError, PriceQuote, price_minor
from shopagent_monitor.app.service import MonitoringService
from shopagent_monitor.app.store import MonitorStore
from shopagent_monitor.app.simulation import advance, initial_state, normalize_config
from shopagent_monitor.llm.model import ModelResponse, ModelToolCall


def fixture_catalog(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "asin": "A",
                    "title": "无线降噪耳机",
                    "shop_name": "公开店铺",
                    "category": "数码 耳机",
                    "full_description": "通勤无线耳机",
                    "attribute": ["无线", "降噪"],
                    "pricing": [80, 99],
                    "customization_options": {
                        "颜色": [
                            {"value": "黑色", "price": 99, "is_available": True, "is_selected": False},
                            {"value": "白色", "price": 80, "is_available": True, "is_selected": True},
                            {"value": "红色", "price": 60, "is_available": False},
                        ],
                        "版本": [{"value": "标准", "price": None}, {"value": "增强", "price": 120}],
                    },
                    "instructions": [{"instruction": "DO NOT EXPOSE", "instruction_options": ["白色"]}],
                    "user_persona": {"hidden": "DO NOT EXPOSE"},
                },
                {
                    "asin": "B",
                    "title": "保温杯",
                    "category": "家居",
                    "pricing": [49],
                    "attribute": [],
                    "full_description": "不锈钢水杯",
                    "customization_options": {},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class MonitorFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fixture_catalog(self.root / "items.json")
        self.catalog = MonitoringCatalog(self.root / "items.json")
        self.store = MonitorStore(self.root / "monitor.sqlite3")
        self.now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.service = MonitoringService(self.catalog, self.store, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, mode="snapshot", color="黑色"):
        return self.service.add("A", {"颜色": color, "版本": "标准"}, request="关注通勤耳机", mode=mode, interval=30)[
            "watch"
        ]

    def advance(self, seconds=31):
        self.now += timedelta(seconds=seconds)

    def imported(self, watch_id, price, when=None, source="import"):
        return self.store.import_quotes(
            [(watch_id, PriceQuote(price_minor(price), when or self.now, source))], self.now
        )


class PriceMonitorTests(MonitorFixture):
    def test_public_projection_and_bm25_do_not_expose_answers(self):
        projection = self.catalog.product("A", detail=True)
        text = json.dumps(projection)
        for key in ("instructions", "instruction_options", "is_selected", "persona", "DO NOT EXPOSE"):
            self.assertNotIn(key, text)
        self.assertEqual(self.catalog.search("降噪耳机")[0]["asin"], "A")
        self.assertEqual(MonitoringAgent(self.catalog).search("降噪耳机")["engine"], "catalog")

    def test_exact_variant_prices_and_reject_incomplete_unavailable_conflicting(self):
        black = self.add()
        white = self.add(color="白色")
        self.assertEqual(black["current_price"], "99.00")
        self.assertEqual(white["current_price"], "80.00")
        self.assertNotEqual(black["id"], white["id"])
        for choices in (
            {"颜色": "黑色"},
            {"颜色": "红色", "版本": "标准"},
            {"颜色": "黑色", "版本": "增强"},
            {"A的尺码": "M"},
        ):
            with self.assertRaises(MonitorError):
                self.service.add("A", choices, request="x")

    def test_first_sample_duplicate_watch_tie_and_new_low(self):
        watch = self.add()
        self.assertEqual(self.store.alerts(), [])
        self.assertEqual(self.add()["id"], watch["id"])
        self.advance()
        self.assertEqual(self.imported(watch["id"], "90.00")["alerts_created"], 1)
        self.assertEqual(self.imported(watch["id"], "90.00")["duplicates"], 1)
        self.advance()
        self.assertEqual(self.imported(watch["id"], "90")["alerts_created"], 0)
        self.advance()
        self.imported(watch["id"], "95")
        self.advance()
        self.assertEqual(self.imported(watch["id"], "89.99")["alerts_created"], 1)
        self.assertEqual(len(self.store.alerts()), 2)
        self.assertEqual(self.store.get(watch["id"])["low_price"], "89.99")

    def test_snapshot_polling_does_not_fabricate_new_prices(self):
        watch = self.add()
        self.advance()
        result = self.service.run_due()
        self.assertEqual(result[0]["status"], "ok")
        self.assertFalse(result[0]["inserted"])
        self.assertEqual(self.store.get(watch["id"])["sample_count"], 1)

    def test_simulation_is_separate_and_cannot_modify_snapshot(self):
        real, simulated = self.add(), self.add(mode="simulation")
        self.advance()
        with self.assertRaises(MonitorError):
            self.service.simulate(real["id"], "50")
        self.service.simulate(simulated["id"], "50")
        self.assertEqual(self.store.get(real["id"])["low_price"], "99.00")
        self.assertEqual(self.store.get(simulated["id"])["low_price"], "50.00")
        self.assertEqual(self.store.alerts()[0]["mode"], "simulation")
        with self.assertRaises(MonitorError):
            self.imported(simulated["id"], "40")

    def test_import_is_atomic_including_alerts_and_timestamp_conflicts(self):
        watch = self.add()
        self.advance()
        with self.assertRaises(MonitorError):
            self.store.import_quotes(
                [
                    (watch["id"], PriceQuote(8000, self.now, "import")),
                    ("missing", PriceQuote(5000, self.now, "import")),
                ],
                self.now,
            )
        self.assertEqual(self.store.stats()["observation_count"], 1)
        self.assertEqual(self.store.alerts(), [])
        self.imported(watch["id"], 80)
        with self.assertRaises(MonitorError):
            self.imported(watch["id"], 70)
        self.assertEqual(self.store.get(watch["id"])["current_price"], "80.00")

    def test_old_backfill_changes_low_but_not_current_or_notification(self):
        watch = self.add()
        self.imported(watch["id"], 70, self.now - timedelta(days=1))
        current = self.store.get(watch["id"])
        self.assertEqual(current["low_price"], "70.00")
        self.assertEqual(current["current_price"], "99.00")
        self.assertEqual(self.store.alerts(), [])
        self.advance()
        self.assertEqual(self.imported(watch["id"], 80)["alerts_created"], 0)

    def test_money_and_observation_validation(self):
        for invalid in (0, -1, "NaN", "Infinity", True, "0.001", "1000000001", None):
            with self.assertRaises(MonitorError):
                price_minor(invalid)
        watch = self.add()
        with self.assertRaises(MonitorError):
            self.imported(watch["id"], 50, self.now + timedelta(seconds=1))
        with self.assertRaises(MonitorError):
            self.store.import_quotes([(watch["id"], PriceQuote(100, self.now, "import", "USD"))], self.now)

    def test_concurrent_imports_create_one_observation_and_alert(self):
        watch = self.add()
        self.advance()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.imported(watch["id"], 80), range(12)))
        self.assertEqual(sum(r["inserted"] for r in results), 1)
        self.assertEqual(len(self.store.alerts()), 1)

    def test_leases_prevent_duplicate_check_and_expire(self):
        watch = self.add()
        other = MonitorStore(self.root / "monitor.sqlite3")
        token = self.store.claim(watch["id"], self.now, force=True)
        self.assertIsNotNone(token)
        self.assertIsNone(other.claim(watch["id"], self.now, force=True))
        self.advance(121)
        replacement = other.claim(watch["id"], self.now, force=True)
        self.assertIsNotNone(replacement)
        with self.assertRaises(MonitorError):
            self.store.finish_check(watch["id"], token, self.now)
        self.store.finish_check(watch["id"], replacement, self.now)

    def test_pause_resume_restart_and_failure_recovery(self):
        watch = self.add(mode="simulation")
        self.store.update(watch["id"], active=False, interval=None, now=self.now)
        self.advance()
        self.assertEqual(self.service.run_due(), [])
        with self.assertRaises(MonitorError):
            self.service.refresh(watch["id"])
        self.store.update(watch["id"], active=True, interval=None, now=self.now)

        class FailingProvider:
            def fetch(self, watch, *, now):
                raise TimeoutError("private upstream details")

        self.service.providers["simulation"] = FailingProvider()
        self.advance()
        self.assertEqual(self.service.run_due()[0]["status"], "error")
        saved = MonitorStore(self.root / "monitor.sqlite3").get(watch["id"])
        self.assertEqual(saved["sample_count"], 1)
        self.assertIn("TimeoutError", saved["last_error"])
        self.assertNotIn("private", saved["last_error"])

    def test_agent_native_loop_only_finishes_with_seen_ids(self):
        class Backend:
            def __init__(self, bad=False):
                self.calls = 0
                self.bad = bad

            def generate(self, **kwargs):
                self.calls += 1
                call = (
                    ModelToolCall("search", {"query": "降噪耳机"}, "s")
                    if self.calls == 1
                    else ModelToolCall(
                        "finish",
                        {"candidates": [{"asin": "invented" if self.bad else "A", "reason": "公开标题包含无线降噪"}]},
                        "f",
                    )
                )
                return ModelResponse(text="", tool_call=call)

        result = MonitoringAgent(self.catalog, backend=Backend()).search("通勤耳机")
        self.assertEqual(result["engine"], "model")
        self.assertEqual(result["products"][0]["asin"], "A")
        bad = MonitoringAgent(self.catalog, backend=Backend(True)).search("降噪耳机")
        self.assertEqual(bad["engine"], "partial")
        self.assertFalse(bad["selection_complete"])
        self.assertTrue(all(p["asin"] != "invented" for p in bad["products"]))


class PriceSimulationTests(MonitorFixture):
    def simulated(self, engine="event", scenario=None, seed=42):
        return self.service.add(
            "A",
            {"颜色": "黑色", "版本": "标准"},
            request="耳机",
            mode="simulation",
            interval=30,
            simulation={"engine": engine, "scenario": scenario, "seed": seed, "tick_seconds": 30},
        )["watch"]

    def test_same_tick_refresh_is_idempotent_and_sampling_does_not_drift(self):
        watch = self.simulated()
        self.advance(10)
        for _ in range(4):
            self.assertFalse(self.service.refresh(watch["id"])["inserted"])
        self.assertEqual(self.store.get(watch["id"])["sample_count"], 1)
        self.advance(21)
        self.assertTrue(self.service.refresh(watch["id"])["inserted"])
        sampled = self.store.history(watch["id"])[-1]
        self.assertEqual(sampled["simulation_tick"], 1)
        self.assertTrue(sampled["observed_at"].endswith("00:00:30.000000+00:00"))
        self.assertTrue(self.store.get(watch["id"])["next_check_at"].endswith("00:01:00.000000+00:00"))
        self.assertFalse(self.service.refresh(watch["id"])["inserted"])

    def test_event_sequence_is_bounded_has_holds_and_restores_normal_price(self):
        config = normalize_config()
        state, events, restored = initial_state(10000), set(), False
        for tick in range(1, 600):
            prior_normal = state["normal_minor"]
            state = advance(state, config, "product-variant", 10000, tick)
            events.add(state["event"])
            self.assertGreaterEqual(state["normal_minor"], 9000)
            self.assertLessEqual(state["normal_minor"], 11000)
            self.assertGreaterEqual(state["amount_minor"], 6750)
            self.assertLessEqual(state["amount_minor"], 11000)
            if state["event"] == "promotion_end":
                self.assertEqual(state["amount_minor"], prior_normal)
                restored = True
        self.assertTrue(restored)
        self.assertTrue({"unchanged", "adjustment", "promotion_start", "promotion_hold", "promotion_end"} <= events)

    def test_event_sampling_order_and_restart_do_not_change_sequence(self):
        config = normalize_config()
        sparse = advance(initial_state(10000), config, "same-sku", 10000, 100)
        dense = initial_state(10000)
        for tick in range(1, 101):
            dense = advance(dense, config, "same-sku", 10000, tick)
        self.assertEqual(sparse, dense)
        self.assertNotEqual(
            sparse, advance(initial_state(10000), normalize_config({"seed": 7}), "same-sku", 10000, 100)
        )
        watch = self.simulated()
        self.advance(65)
        first = self.store.simulation_quote(watch["simulation_run_id"], self.now)
        reopened = MonitorStore(self.root / "monitor.sqlite3")
        self.assertEqual(first, reopened.simulation_quote(watch["simulation_run_id"], self.now))
        self.assertEqual(self.service.refresh(watch["id"])["status"], "ok")

    def test_replay_exact_prices_alerts_completion_and_repeat_reads(self):
        watch = self.simulated("replay", "new_lows")
        for _ in range(7):
            self.advance(30)
            self.assertEqual(self.service.run_due()[0]["status"], "ok")
        self.assertEqual(
            [p["price"] for p in self.store.history(watch["id"])],
            ["99.00", "99.00", "94.05", "94.05", "103.95", "89.10", "89.10", "84.15"],
        )
        self.assertEqual(len(self.store.alerts()), 3)
        completed = self.store.get(watch["id"])
        self.assertTrue(completed["simulation"]["complete"])
        self.assertFalse(completed["active"])
        self.advance(300)
        self.assertEqual(self.service.run_due(), [])
        self.assertEqual(self.store.get(watch["id"])["sample_count"], 8)

    def test_replay_promotion_ends_at_original_price_and_stable_has_no_alerts(self):
        promotion, stable = self.simulated("replay", "promotion"), self.simulated("replay", "stable")
        for _ in range(7):
            self.advance(30)
            self.service.run_due()
        self.assertEqual(
            [p["price"] for p in self.store.history(promotion["id"])],
            ["99.00", "99.00", "79.20", "79.20", "99.00", "89.10", "89.10", "99.00"],
        )
        self.assertEqual(len([a for a in self.store.alerts() if a["watch_id"] == promotion["id"]]), 1)
        self.assertEqual(len([a for a in self.store.alerts() if a["watch_id"] == stable["id"]]), 0)

    def test_replay_failure_never_becomes_zero_and_recovers(self):
        watch = self.simulated("replay", "failure_recovery")
        for _ in range(2):
            self.advance(30)
            self.assertEqual(self.service.run_due()[0]["status"], "error")
            self.assertEqual(self.store.get(watch["id"])["sample_count"], 1)
        self.assertEqual(self.store.alerts(), [])
        self.advance(30)
        self.assertEqual(self.service.run_due()[0]["status"], "ok")
        result = self.store.get(watch["id"])
        self.assertEqual(result["current_price"], "94.05")
        self.assertIsNone(result["last_error"])
        self.assertEqual(len(self.store.alerts()), 1)
        self.assertTrue(all(p["amount_minor"] > 0 for p in self.store.history(watch["id"])))

    def test_replay_is_immutable_and_restart_keeps_old_history(self):
        watch = self.simulated("replay", "continuous_lows")
        self.advance(30)
        self.service.run_due()
        before = self.store.history(watch["id"])
        with self.assertRaises(MonitorError):
            self.service.simulate(watch["id"], "1.00")
        restarted = self.service.restart_replay(watch["id"])["watch"]
        self.assertNotEqual(restarted["id"], watch["id"])
        self.assertEqual(restarted["current_price"], "99.00")
        self.assertEqual(restarted["simulation"]["tick"], 0)
        self.assertFalse(self.store.get(watch["id"])["active"])
        self.assertEqual(self.store.history(watch["id"]), before)
        self.assertEqual(len(self.store.alerts()), 1)
        self.assertEqual(self.simulated("replay", "continuous_lows")["id"], restarted["id"])
        # Two restarts can share a timestamp; dedup must still select the last run.
        newest = self.service.restart_replay(restarted["id"])["watch"]
        self.assertEqual(self.simulated("replay", "continuous_lows")["id"], newest["id"])
        self.store.delete(newest["id"])
        self.store.delete(restarted["id"])
        self.store.delete(watch["id"])
        self.advance(300)
        self.assertEqual(self.simulated("replay", "continuous_lows")["simulation"]["tick"], 0)

    def test_config_identity_and_invalid_settings(self):
        event = self.simulated()
        self.assertEqual(event["id"], self.simulated()["id"])
        self.assertNotEqual(event["id"], self.simulated(seed=7)["id"])
        self.assertNotEqual(event["id"], self.simulated("replay", "new_lows")["id"])
        for invalid in (
            [],
            {"seed": True},
            {"seed": -1},
            {"tick_seconds": 1},
            {"scenario": "x"},
            {"engine": "replay", "scenario": "x"},
            {"unknown": 1},
        ):
            with self.assertRaises(MonitorError):
                normalize_config(invalid)
        with self.assertRaises(MonitorError):
            self.service.add("B", {}, request="杯子", simulation={"engine": "event"})
        with self.assertRaises(MonitorError):
            self.service.add(
                "B",
                {},
                request="杯子",
                mode="simulation",
                interval=60,
                simulation={"engine": "replay", "tick_seconds": 30},
            )
        replay = self.simulated("replay", "new_lows")
        with self.assertRaises(MonitorError):
            self.store.update(replay["id"], active=None, interval=60, now=self.now)
        self.assertEqual(self.store.get(replay["id"])["interval_seconds"], 30)
        self.advance(7)
        self.store.update(event["id"], active=True, interval=30, now=self.now)
        self.assertTrue(self.store.get(event["id"])["next_check_at"].endswith("00:00:30.000000+00:00"))

    def test_legacy_database_migration_preserves_observations_and_alerts(self):
        watch = self.simulated()
        self.advance()
        self.service.simulate(watch["id"], "70.00")
        before_history, before_alerts = self.store.history(watch["id"]), self.store.alerts()
        with closing(sqlite3.connect(self.root / "monitor.sqlite3")) as db:
            db.execute("ALTER TABLE watches DROP COLUMN simulation_run_id")
            db.execute("ALTER TABLE observations DROP COLUMN event")
            db.execute("ALTER TABLE observations DROP COLUMN simulation_tick")
            db.execute("DROP TABLE simulation_runs")
        upgraded = MonitorStore(self.root / "monitor.sqlite3", migration_now=self.now)
        saved = upgraded.get(watch["id"])
        self.assertEqual(saved["current_price"], "70.00")
        self.assertEqual(saved["baseline_price"], "99.00")
        self.assertEqual(saved["sample_count"], len(before_history))
        self.assertEqual(upgraded.alerts(), before_alerts)
        self.assertEqual(saved["simulation"]["base_price"], "70.00")
        self.assertEqual(saved["simulation"]["engine"], "event")
        twice = MonitorStore(self.root / "monitor.sqlite3", migration_now=self.now)
        self.assertEqual(twice.get(watch["id"])["simulation_run_id"], saved["simulation_run_id"])


try:
    from fastapi.testclient import TestClient
    from shopagent_monitor.app.web import create_app
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "install the web extra to run HTTP integration tests")
class PriceMonitorWebTests(MonitorFixture):
    def test_simulation_api_presets_replay_and_restart(self):
        app = create_app(service=self.service, model_config=None, scheduler_enabled=False)
        with TestClient(app) as client:
            self.assertEqual(len(client.get("/api/simulation-presets").json()["scenarios"]), 5)
            body = {
                "asin": "B",
                "selections": {},
                "mode": "simulation",
                "interval_seconds": 30,
                "simulation": {"engine": "replay", "scenario": "new_lows", "tick_seconds": 30},
            }
            watch = client.post("/api/watches", json=body).json()["watch"]
            self.assertEqual(watch["simulation"]["scenario_name"], "同价、回涨与再次新低")
            self.advance(60)
            self.assertEqual(client.post(f"/api/watches/{watch['id']}/refresh").json()["status"], "ok")
            self.assertEqual(client.get("/api/alerts").json()["alerts"][0]["price"], "46.55")
            self.assertEqual(client.post(f"/api/watches/{watch['id']}/simulate", json={"price": "1"}).status_code, 400)
            restarted = client.post(f"/api/watches/{watch['id']}/replay/restart").json()["watch"]
            self.assertEqual(restarted["sample_count"], 1)
            self.assertEqual(restarted["simulation"]["tick"], 0)
            self.assertEqual(client.post("/api/watches", json={**body, "simulation": {"seed": True}}).status_code, 422)

    def test_http_flow_import_alert_read_and_delete(self):
        app = create_app(service=self.service, model_config=None, scheduler_enabled=False)
        with TestClient(app) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/static/app.js").status_code, 200)
            self.assertEqual(client.get("/api/status").json()["catalog_count"], 2)
            results = client.post("/api/search", json={"description": "降噪耳机"}).json()
            self.assertEqual(results["products"][0]["asin"], "A")
            body = {"asin": "A", "selections": {"颜色": "黑色", "版本": "标准"}, "request": "耳机"}
            created = client.post("/api/watches", json=body)
            self.assertEqual(created.status_code, 200)
            watch = created.json()["watch"]
            self.assertFalse(client.post("/api/watches", json=body).json()["created"])
            self.advance()
            imported = client.post(
                "/api/prices/import",
                json={
                    "observations": [{"watch_id": watch["id"], "price": "88.88", "observed_at": self.now.isoformat()}]
                },
            )
            self.assertEqual(imported.json()["alerts_created"], 1)
            alert = client.get("/api/alerts").json()["alerts"][0]
            self.assertEqual(client.post(f"/api/alerts/{alert['id']}/read").status_code, 200)
            self.assertEqual(client.get("/api/status").json()["unread_count"], 0)
            self.assertEqual(client.post("/api/watches", json={**body, "interval_seconds": 1}).status_code, 422)
            self.assertEqual(
                client.post("/api/watches", json=body, headers={"Origin": "https://evil.example"}).status_code, 403
            )
            self.assertEqual(client.delete(f"/api/watches/{watch['id']}").status_code, 200)
            self.assertEqual(client.get("/api/status").json()["observation_count"], 0)
            self.assertEqual(client.get("/api/alerts").json()["alerts"], [])

    def test_background_lifespan_scheduler_really_runs(self):
        watch = self.add(mode="simulation")
        self.advance()
        app = create_app(service=self.service, model_config=None, scheduler_enabled=True, poll_seconds=0.03)
        with TestClient(app) as client:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if client.get("/api/status").json()["observation_count"] >= 2:
                    break
                time.sleep(0.02)
            self.assertEqual(self.store.get(watch["id"])["sample_count"], 2)


if __name__ == "__main__":
    unittest.main()
