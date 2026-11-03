from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import socket
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote
from urllib.error import HTTPError, URLError

try:
    from fastapi.testclient import TestClient
    from shopagent_monitor.app.web import create_app
except ImportError:
    TestClient = None

from shopagent_monitor.app.agent import MonitoringAgent
from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.domain import MonitorError
from shopagent_monitor.app.model_settings import ModelSettings, ModelSettingsInput
from shopagent_monitor.app.model_errors import connection_error
from shopagent_monitor.app.model_requests import generate_bounded
from shopagent_monitor.app.service import MonitoringService
from shopagent_monitor.app.store import MonitorStore
from shopagent_monitor.llm.messages import ModelContext, UserMessage
from shopagent_monitor.llm.model import (
    ModelConfig,
    ModelContextBudgetError,
    ModelFailure,
    ModelResponse,
    ModelToolCall,
    create_model_backend,
)


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        items = self.root / "items.json"
        items.write_text(
            json.dumps([{"asin": "A", "title": "保温杯", "pricing": [50], "customization_options": {}}]),
            encoding="utf-8",
        )
        self.catalog = MonitoringCatalog(items)
        self.path = self.root / "secrets/model.json"
        self.models = ModelSettings(MonitoringAgent(self.catalog), path=self.path)

    def body(self, **changes):
        # These existing protocol tests exercise complete JSON envelopes without
        # transport retries. Streaming and retry contracts have separate tests.
        changes.setdefault("stream", False)
        changes.setdefault("max_retries", 0)
        return ModelSettingsInput(model="test-model", base_url="http://127.0.0.1:8080/v1", **changes)

    def test_reasoning_and_context_defaults_and_validation(self):
        self.assertEqual(self.models.public()["reasoning_effort"], "none")
        self.assertEqual(self.models.public()["max_context_tokens"], 24576)
        for changes in (
            {"reasoning_effort": "unknown"},
            {"max_context_tokens": True},
            {"max_context_tokens": 2047},
            {"max_context_tokens": 2097153},
            {"max_context_tokens": 4096, "max_output_tokens": 4096},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.body(**changes)

    def test_reasoning_and_context_survive_save_reload_and_legacy_files(self):
        self.models.save(self.body(reasoning_effort="high", max_context_tokens=65536))
        loaded = ModelSettings(MonitoringAgent(self.catalog), path=self.path)
        self.assertEqual(loaded.public()["reasoning_effort"], "high")
        self.assertEqual(loaded.agent.config.max_context_tokens, 65536)
        self.assertEqual(loaded.agent.advisor.max_context_tokens, 65536)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw.pop("reasoning_effort")
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        legacy = ModelSettings(MonitoringAgent(self.catalog), path=self.path)
        self.assertIsNone(legacy.load_error)
        self.assertEqual(legacy.public()["reasoning_effort"], "high")
        self.assertEqual(legacy.public()["max_context_tokens"], 65536)
        raw.pop("max_context_tokens")
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(
            ModelSettings(MonitoringAgent(self.catalog), path=self.path).public()["max_context_tokens"], 24576
        )

    def test_new_install_defaults_to_deepseek_without_starting_model_requests(self):
        public = self.models.public()
        self.assertEqual(public["model"], "deepseek-v4.1-flash")
        self.assertEqual(public["provider"], "openai-responses")
        self.assertTrue(public["api_key_required"])
        self.assertFalse(public["enabled"])
        self.assertIsNone(self.models.agent.backend)
        example = Path(__file__).resolve().parents[1] / "examples/model-deepseek-responses.json"
        config = ModelConfig.from_file(example)
        self.assertEqual(config.model, public["model"])
        self.assertEqual(config.provider, public["provider"])

    def test_removed_provider_is_rejected_before_any_model_request(self):
        for provider in ("gemini", "google", "google-gemini", "gemini-generate-content"):
            with self.subTest(provider=provider):
                with self.assertRaises(ValueError):
                    self.body(provider=provider)
                with self.assertRaisesRegex(ModelFailure, "unsupported provider"):
                    ModelConfig.from_mapping({"provider": provider, "model": "test-model"})
                with patch("shopagent_monitor.llm.model.urllib.request.urlopen") as request:
                    with self.assertRaisesRegex(ModelFailure, "unsupported provider"):
                        create_model_backend(ModelConfig(provider=provider, model="test-model", api_key_required=False))
                    request.assert_not_called()

    def test_context_limit_reserves_output_and_prevents_oversized_search_or_advice(self):
        backend = Mock()
        context = ModelContext(system_prompt="Test", messages=(UserMessage(role="user", content="short"),), tools=())
        # Input alone fits this window; the reserved output makes the complete request exceed it.
        with self.assertRaises(ModelContextBudgetError):
            generate_bounded(backend, context=context, max_output_tokens=2048, max_context_tokens=2048)
        backend.generate.assert_not_called()
        generate_bounded(backend, context=context, max_output_tokens=128, max_context_tokens=2048)
        self.assertEqual(backend.generate.call_count, 1)
        backend.reset_mock()
        agent = MonitoringAgent(
            self.catalog,
            ModelConfig(
                provider="openai-responses",
                model="test",
                api_key_required=False,
                max_context_tokens=2048,
                max_output_tokens=768,
            ),
            backend=backend,
        )
        self.assertEqual(agent.search("保温杯" * 4000)["engine"], "catalog")
        backend.generate.assert_not_called()
        backend.generate.return_value = ModelResponse(text="", tool_call=ModelToolCall("get_monitoring_summary", {}))
        evidence = {
            "product": {"title": "保温杯" * 4000},
            "preferences": {},
            "metrics": {},
            "recent_quotes": [],
            "reasons": {},
            "allowed_decisions": [],
        }
        with self.assertRaises(ModelContextBudgetError):
            agent.advisor._model_advice(evidence)
        self.assertEqual(backend.generate.call_count, 1)

    def test_save_hot_swap_restore_and_disable_share_one_semaphore(self):
        original = self.models.agent
        saved = self.models.save(self.body(max_output_tokens=256))
        self.assertTrue(saved["enabled"])
        self.assertNotEqual(saved["revision"], ModelSettings(original).public()["revision"])
        self.assertIsNot(self.models.agent, original)
        self.assertIs(self.models.agent._model_lock, original._model_lock)
        self.assertIs(self.models.agent.advisor.backend, self.models.agent.backend)
        self.assertEqual(self.models.agent.advisor.max_output_tokens, 256)
        loaded = ModelSettings(MonitoringAgent(self.catalog), path=self.path)
        self.assertEqual(loaded.public()["model"], "test-model")
        self.assertIsNotNone(loaded.agent.backend)
        loaded.save(self.body(enabled=False))
        restored = ModelSettings(MonitoringAgent(self.catalog), path=self.path)
        self.assertIsNone(restored.agent.backend)
        self.assertEqual(restored.agent.search("保温杯")["engine"], "catalog")
        forced = ModelSettings(original, path=self.path, start_disabled=True)
        self.assertFalse(forced.public()["enabled"])

    def test_secret_is_separate_retained_replaced_and_cleared(self):
        saved = self.models.save(self.body(api_key_required=True, api_key="fixture-key-one"))
        self.assertTrue(saved["has_api_key"])
        self.assertNotIn("fixture-key", json.dumps(saved))
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("fixture-key", json.dumps(raw))
        first = self.path.parent / raw["credentials_file"]
        self.assertEqual(json.loads(first.read_text())["api_key"], "fixture-key-one")
        self.models.save(self.body(api_key_required=True))
        self.assertEqual(self.models.agent.backend._api_key, "fixture-key-one")
        self.models.save(self.body(api_key_required=True, api_key="fixture-key-two"))
        self.assertFalse(first.exists())
        restored = ModelSettings(MonitoringAgent(self.catalog), path=self.path)
        self.assertEqual(restored.agent.backend._api_key, "fixture-key-two")
        restored.save(self.body(clear_api_key=True))
        self.assertFalse(restored.public()["has_api_key"])
        self.assertEqual(list(self.path.parent.glob("credentials-*.json")), [])

    def test_switching_endpoint_does_not_reuse_a_credential(self):
        self.models.save(self.body(api_key_required=True, api_key="fixture-secret"))
        changed = self.body(api_key_required=True).model_copy(update={"base_url": "https://other.invalid/v1"})
        with self.assertRaisesRegex(MonitorError, "重新输入"):
            self.models.save(changed)
        self.assertEqual(self.models.public()["base_url"], "http://127.0.0.1:8080/v1")
        self.models.save(changed.model_copy(update={"api_key_required": False}))
        self.assertFalse(self.models.public()["has_api_key"])
        self.assertIsNone(self.models.agent.backend._api_key)

    def test_write_failure_retains_running_agent_and_configuration(self):
        self.models.save(self.body())
        before = self.path.read_bytes()
        agent, revision = self.models.agent, self.models.revision
        with patch("shopagent_monitor.app.model_settings._atomic_json", side_effect=OSError("denied")):
            with self.assertRaises(MonitorError):
                self.models.save(self.body(api_key="fixture-secret"))
        self.assertIs(self.models.agent, agent)
        self.assertEqual(self.models.revision, revision)
        self.assertEqual(self.path.read_bytes(), before)

    def test_external_startup_credentials_are_not_deleted_on_web_save(self):
        self.path.parent.mkdir()
        external = self.path.parent / "credentials-external.json"
        external.write_text('{"api_key":"fixture-external-key"}', encoding="utf-8")
        config = ModelConfig.from_mapping(
            {
                "provider": "openai-responses",
                "model": "test-model",
                "base_url": "http://127.0.0.1:8080/v1",
                "credentials_file": str(external),
            }
        )
        models = ModelSettings(MonitoringAgent(self.catalog, config), path=self.path)
        models.save(self.body(api_key_required=True))
        self.assertTrue(external.exists())
        self.assertEqual(models.agent.backend._api_key, "fixture-external-key")

    def test_test_uses_draft_does_not_save_and_rejects_bad_tools(self):
        before = self.models.public()
        response = ModelResponse(text="", tool_call=ModelToolCall("connection_check", {"ok": True}))
        with patch("shopagent_monitor.app.model_settings.create_model_backend") as factory:
            factory.return_value.generate.return_value = response
            result = self.models.test(self.body(reasoning_effort="medium", max_context_tokens=32768))
            self.assertTrue(result["ok"])
            tested = factory.call_args.args[0]
            self.assertEqual(tested.reasoning_effort, "medium")
            self.assertEqual(tested.max_context_tokens, 32768)
            self.assertEqual(factory.return_value.generate.call_args.kwargs["max_output_tokens"], 768)
            context = factory.return_value.generate.call_args.kwargs["context"]
            self.assertEqual(context.tools[0]["name"], "connection_check")
            factory.return_value.generate.return_value = ModelResponse(text="", tool_call=ModelToolCall("buy", {}))
            self.assertFalse(self.models.test(self.body())["ok"])
            factory.return_value.generate.side_effect = RuntimeError("fixture-secret provider URL")
            self.assertNotIn("fixture-secret", json.dumps(self.models.test(self.body(api_key="fixture-secret"))))
        self.assertFalse(self.path.exists())
        self.assertEqual(self.models.public(), before)
        self.assertTrue(self.models.agent._model_lock.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(MonitorError, "正在处理"):
                self.models.test(self.body())
        finally:
            self.models.agent._model_lock.release()

    def test_corrupt_settings_do_not_prevent_opening_settings_page(self):
        self.path.parent.mkdir()
        self.path.write_text("broken", encoding="utf-8")
        models = ModelSettings(MonitoringAgent(self.catalog), path=self.path)
        self.assertIsNotNone(models.public()["load_error"])
        self.assertIsNone(models.agent.backend)

    def test_native_backend_http_errors_show_status_and_redacted_provider_reason(self):
        key = "sk-fixture-private-key"
        for provider in ("openai-responses", "openai-chat"):
            for status in (400, 401, 403, 404, 405, 429, 503):
                with self.subTest(provider=provider, status=status):
                    raw = json.dumps({"error": {"message": f"Model unavailable; received key {key}"}}).encode()
                    exc = HTTPError("https://provider.invalid/v1", status, "upstream failure", {}, BytesIO(raw))
                    with patch("shopagent_monitor.llm.model.urllib.request.urlopen", side_effect=exc):
                        result = self.models.test(self.body(provider=provider, api_key_required=True, api_key=key))
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["error"]["http_status"], status)
                    self.assertIn(f"HTTP {status}", result["message"])
                    self.assertIn("Model unavailable", result["error"]["detail"])
                    self.assertIn("[密钥已隐藏]", result["error"]["detail"])
                    self.assertNotIn(key, json.dumps(result))
                    self.assertNotIn("fixture-private-key", json.dumps(result))
                    self.assertNotIn("?", result["error"]["endpoint"])

    def test_transport_errors_are_classified_and_keep_the_underlying_reason(self):
        failures = [
            (URLError(ConnectionRefusedError(10061, "target actively refused connection")), "connection_refused"),
            (TimeoutError("The read operation timed out"), "timeout"),
            (URLError(socket.gaierror(-2, "Name or service not known")), "dns_error"),
            (URLError(ssl.SSLError("certificate verify failed")), "tls_error"),
            (URLError("network unreachable"), "network_error"),
        ]
        for exc, kind in failures:
            with self.subTest(kind=kind):
                with patch("shopagent_monitor.app.model_settings.create_model_backend") as factory:
                    wrapper = ModelFailure("provider request failed")
                    wrapper.__cause__ = exc
                    factory.return_value.generate.side_effect = wrapper
                    result = self.models.test(self.body())
                self.assertEqual(result["error"]["kind"], kind)
                self.assertNotIn("provider request failed", result["error"]["detail"])
                self.assertTrue(result["error"]["detail"])
                self.assertIsNone(result["error"]["http_status"])

    def test_diagnostics_remove_known_encoded_environment_and_truncated_credentials(self):
        key = "opaque-fixture/key+secret-123"
        config = ModelConfig(
            provider="openai-responses",
            model="test-model",
            base_url="https://provider.invalid/v1",
            api_key_env="SHOPAGENT_ERROR_TEST_KEY",
        )
        with patch.dict("os.environ", {"SHOPAGENT_ERROR_TEST_KEY": key}):
            raw = (
                f"HTTP 401: raw={key}; encoded={quote(key, safe='')}; "
                f'Authorization: Bearer {key}; api_key="other-private-value"; '
                f"URL=https://user:password@provider.invalid/v1?key={quote(key, safe='')}&trace=private"
            )
            result = connection_error(RuntimeError(raw), config)
            rendered = json.dumps(result, ensure_ascii=False)
            for secret in (key, quote(key, safe=""), "other-private-value", "user:password", "trace=private"):
                self.assertNotIn(secret, rendered)
            self.assertIn("HTTP 401", rendered)
            truncated = connection_error(RuntimeError("HTTP 401: received " + key[:18]), config)
            self.assertNotIn(key[:8], json.dumps(truncated))
            oversized = connection_error(RuntimeError(("diagnostic " * 2000) + key), config)
            self.assertLess(len(oversized["error"]["detail"]), 1550)

    def test_missing_credentials_and_wrong_tool_arguments_have_concrete_diagnostics(self):
        missing = self.models.test(self.body(api_key_required=True))
        self.assertEqual(missing["error"]["kind"], "missing_api_key")
        with patch("shopagent_monitor.app.model_settings.create_model_backend") as factory:
            factory.return_value.generate.return_value = ModelResponse(text="", tool_call=ModelToolCall("buy", {}))
            result = self.models.test(self.body())
        self.assertEqual(result["error"]["kind"], "invalid_tool_call")
        self.assertIn("buy", result["error"]["detail"])
        self.assertIn("connection_check", result["error"]["detail"])

    def test_local_settings_do_not_pick_up_an_unrelated_global_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unrelated-fixture-secret"}):
            self.assertFalse(self.models.public()["has_api_key"])
            with self.assertRaises(MonitorError):
                self.models.save(self.body(api_key_required=True))
            self.assertFalse(self.path.exists())

    @unittest.skipIf(TestClient is None, "install the web extra to run HTTP integration tests")
    def test_http_validation_redacts_secrets_and_rejects_cross_site_put(self):
        service = MonitoringService(self.catalog, MonitorStore(self.root / "monitor.sqlite3"))
        app = create_app(service=service, model_config=None, model_settings_path=self.path, scheduler_enabled=False)
        with TestClient(app) as client:
            body = self.body(api_key="fixture-secret").model_dump()
            for invalid in (
                {"api_key": ["fixture-secret"]},
                {"unexpected": "fixture-secret"},
                {"base_url": "https://user:fixture-secret@example.com/v1"},
                {"base_url": "file:///fixture-secret"},
                {"max_output_tokens": True},
                {"reasoning_effort": "fixture-secret"},
                {"max_context_tokens": True},
                {"max_context_tokens": 2048, "max_output_tokens": 4096},
                {"base_url": "http://example.com/v1?key=fixture-secret"},
            ):
                result = client.put("/api/model-settings", json=body | invalid)
                self.assertEqual(result.status_code, 422)
                self.assertNotIn("fixture-secret", result.text)
            self.assertEqual(
                client.put("/api/model-settings", json=body, headers={"Origin": "https://evil.invalid"}).status_code,
                403,
            )
            saved = client.put("/api/model-settings", json=body)
            self.assertEqual(saved.status_code, 200)
            self.assertNotIn("fixture-secret", saved.text)
            self.assertNotIn("fixture-secret", client.get("/api/model-settings").text)
            updated = client.put(
                "/api/model-settings", json=body | {"reasoning_effort": "medium", "max_context_tokens": 32768}
            ).json()
            self.assertEqual(updated["reasoning_effort"], "medium")
            self.assertEqual(client.get("/api/model-settings").json()["max_context_tokens"], 32768)
            watch = client.post("/api/watches", json={"asin": "A", "selections": {}}).json()["watch"]
            client.put("/api/model-settings", json=body | {"enabled": False})
            status = client.get("/api/status").json()
            self.assertFalse(status["model_enabled"])
            advice = client.post(f"/api/watches/{watch['id']}/advice", json={}).json()
            self.assertEqual(advice["model_revision"], status["model_revision"])
            self.assertEqual(advice["engine"], "rules")

    def test_live_http_protocols_authentication_and_draft_isolation(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers.get("Authorization"), payload))
                if "/responses" in self.path:
                    value = {
                        "output": [
                            {
                                "type": "function_call",
                                "name": "connection_check",
                                "arguments": '{"ok":true}',
                                "call_id": "test",
                            }
                        ]
                    }
                elif "/chat/completions" in self.path:
                    value = {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "test",
                                            "type": "function",
                                            "function": {"name": "connection_check", "arguments": '{"ok":true}'},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                else:
                    self.send_error(404)
                    return
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for provider in ("openai-responses", "openai-chat"):
                body = self.body(provider=provider, api_key_required=True, api_key="fixture-http-key").model_copy(
                    update={"base_url": f"http://127.0.0.1:{server.server_port}/v1"}
                )
                self.assertTrue(self.models.test(body)["ok"], provider)
            self.assertEqual(requests[0][1], "Bearer fixture-http-key")
            self.assertEqual(requests[1][1], "Bearer fixture-http-key")
            self.assertEqual(requests[0][2]["model"], "test-model")
            self.assertEqual(requests[0][2]["max_output_tokens"], 128)
            self.assertNotIn("reasoning", requests[0][2])
            self.assertNotIn("reasoning_effort", requests[1][2])
            for provider in ("openai-responses", "openai-chat"):
                body = self.body(
                    provider=provider,
                    api_key_required=True,
                    api_key="fixture-http-key",
                    reasoning_effort="low",
                    max_context_tokens=32768,
                ).model_copy(update={"base_url": f"http://127.0.0.1:{server.server_port}/v1"})
                self.assertTrue(self.models.test(body)["ok"], provider)
            self.assertEqual(requests[2][2]["reasoning"], {"effort": "low"})
            self.assertEqual(requests[2][2]["max_output_tokens"], 768)
            self.assertEqual(requests[3][2]["reasoning_effort"], "low")
            self.assertNotIn("temperature", requests[3][2])
            self.assertFalse(self.path.exists())
            self.assertFalse(self.models.public()["enabled"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
