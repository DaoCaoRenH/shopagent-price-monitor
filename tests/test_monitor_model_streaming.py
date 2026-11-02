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
from shopagent_monitor.app.model_requests import generate_bounded
from shopagent_monitor.app.model_settings import ModelSettings, ModelSettingsInput
from shopagent_monitor.app.search_progress import SearchCancelled, SearchProgress, operation_events
from shopagent_monitor.llm.messages import ModelContext
from shopagent_monitor.llm.model import (
    ModelConfig,
    ModelEventStream,
    ModelResponse,
    ModelResponseError,
    ModelStreamEvent,
    ModelToolCall,
    OpenAIResponsesBackend,
)

from fastapi.testclient import TestClient
from shopagent_monitor.app.web import create_app
from shopagent_monitor.app.service import MonitoringService
from shopagent_monitor.app.store import MonitorStore


def result(name="connection_check", arguments=None):
    return ModelResponse(
        text="private response",
        tool_call=ModelToolCall(name, {"ok": True} if arguments is None else arguments, "call-test"),
    )


class FakeStreamingBackend:
    def __init__(self, streams):
        self.config = ModelConfig(
            provider="openai-responses", model="test", stream=True, api_key_required=False, max_retries=0
        )
        self.sources = iter(streams)
        self.contexts = []

    def stream(self, **kwargs):
        self.contexts.append(kwargs["context"])
        return ModelEventStream(next(self.sources))

    def generate(self, **kwargs):
        raise AssertionError("non-streaming generate must not be used")


def events(response):
    yield ModelStreamEvent(type="thinking_delta", thinking_delta="private reasoning Bearer fixture-secret")
    yield ModelStreamEvent(type="toolcall_start", tool_name=response.tool_call.name)
    yield ModelStreamEvent(type="toolcall_delta", arguments_delta='{"partial":')
    yield ModelStreamEvent(type="toolcall_end", tool_call=response.tool_call)
    yield ModelStreamEvent(type="done", response=response)


class Fixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dataset = self.root / "items.json"
        dataset.write_text(
            json.dumps([{"asin": "A", "title": "黑色耳机", "pricing": [50], "customization_options": {}}]),
            encoding="utf-8",
        )
        self.catalog = MonitoringCatalog(dataset)


class ModelStreamTests(Fixture, unittest.TestCase):
    def test_stream_and_retry_defaults_persist_and_legacy_switches_are_preserved(self):
        body = ModelSettingsInput(model="test", base_url="http://127.0.0.1:8080/v1")
        self.assertTrue(body.stream)
        self.assertEqual(body.max_retries, 2)
        for value in (-1, 6, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ModelSettingsInput(model="test", base_url=body.base_url, max_retries=value)
        models = ModelSettings(MonitoringAgent(self.catalog), path=self.root / "model.json")
        models.save(body)
        loaded = ModelSettings(MonitoringAgent(self.catalog), path=self.root / "model.json")
        self.assertTrue(loaded.agent.config.stream)
        self.assertEqual(loaded.agent.config.max_retries, 2)
        self.assertEqual(loaded.agent.backend.config.max_retries, 0)
        self.assertEqual(loaded.agent.advisor.max_retries, 2)
        self.assertFalse(ModelSettingsInput(model="test", base_url=body.base_url, provider="openai-chat").stream)
        models.save(body.model_copy(update={"stream": False, "max_retries": 0}))
        loaded = ModelSettings(MonitoringAgent(self.catalog), path=self.root / "model.json")
        self.assertFalse(loaded.agent.config.stream)
        self.assertEqual(loaded.agent.config.max_retries, 0)

    def test_progress_contains_metadata_and_never_model_contents(self):
        backend = FakeStreamingBackend([events(result())])
        progress = []
        response = generate_bounded(
            backend,
            context=ModelContext(system_prompt="test"),
            max_output_tokens=128,
            max_context_tokens=24576,
            on_progress=progress.append,
        )
        self.assertEqual(response.tool_call.arguments, {"ok": True})
        self.assertIn("generating", [p["phase"] for p in progress])
        self.assertIn("tool_arguments", [p["phase"] for p in progress])
        for private in ("private reasoning", "fixture-secret", '"partial"'):
            self.assertNotIn(private, json.dumps(progress))

    def test_timeout_retries_current_turn_preserving_previous_search_and_context(self):
        def timeout():
            raise TimeoutError("read timed out")
            yield

        backend = FakeStreamingBackend(
            [
                events(result("search", {"query": "耳机"})),
                timeout(),
                events(result("inspect_product", {"asin": "A"})),
                events(result("finish", {"candidates": [{"asin": "A", "reason": "公开详情匹配"}]})),
            ]
        )
        config = ModelConfig(
            provider="openai-responses",
            model="test",
            stream=True,
            api_key_required=False,
            max_context_tokens=24576,
            max_retries=2,
        )
        progress = []
        with (
            patch("shopagent_monitor.app.model_requests.time.sleep"),
            patch.object(self.catalog, "search", wraps=self.catalog.search) as search,
        ):
            response = MonitoringAgent(self.catalog, config, backend=backend).search(
                "耳机", on_progress=progress.append
            )
        self.assertEqual(response["engine"], "model")
        self.assertEqual(search.call_count, 1)
        self.assertIs(backend.contexts[1], backend.contexts[2])
        self.assertEqual(len(backend.contexts[1].messages), 3)
        retries = [p for p in progress if "重试 1/2" in p["message"]]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["round"], 2)
        self.assertEqual([s["tool"] for s in response["steps"]], ["search", "inspect_product"])

    def test_partial_stream_timeout_is_discarded_before_retry(self):
        closed = []

        def broken():
            try:
                yield ModelStreamEvent(type="toolcall_delta", arguments_delta='{"query":"wrong')
                raise TimeoutError("read timed out")
            finally:
                closed.append(True)

        backend = FakeStreamingBackend([broken(), events(result("search", {"query": "correct"}))])
        context = ModelContext(system_prompt="test")
        with patch("shopagent_monitor.app.model_requests.time.sleep"):
            response = generate_bounded(
                backend, context=context, max_output_tokens=128, max_context_tokens=24576, max_retries=2
            )
        self.assertEqual(response.tool_call.arguments, {"query": "correct"})
        self.assertEqual(closed, [True])
        self.assertIs(backend.contexts[0], backend.contexts[1])

    def test_retry_exhaustion_is_bounded_and_format_errors_are_not_retried(self):
        for failure, count in (
            (TimeoutError("read timed out"), 3),
            (ConnectionResetError("Connection reset by peer"), 3),
            (ModelResponseError("invalid JSON"), 1),
        ):

            def broken():
                raise failure
                yield

            backend = FakeStreamingBackend([broken() for _ in range(3)])
            progress = []
            with patch("shopagent_monitor.app.model_requests.time.sleep"), self.assertRaises(type(failure)):
                generate_bounded(
                    backend,
                    context=ModelContext(system_prompt="test"),
                    max_output_tokens=128,
                    max_context_tokens=24576,
                    max_retries=2,
                    on_progress=SearchProgress(progress.append).model_callback("model-2"),
                )
            self.assertEqual(len(backend.contexts), count)
            retries = [p for p in progress if p["stage"] == "model_retry"]
            self.assertEqual(len(retries), count - 1)
            self.assertEqual(len({p["step_id"] for p in retries}), count - 1)

    def test_cancel_during_retry_prevents_next_request(self):
        cancelled = threading.Event()

        def broken():
            raise TimeoutError("timed out")
            yield

        backend = FakeStreamingBackend([broken()])

        def progress(event):
            if event["phase"] == "retry":
                cancelled.set()

        with self.assertRaises(SearchCancelled):
            generate_bounded(
                backend,
                context=ModelContext(system_prompt="test"),
                max_output_tokens=128,
                max_context_tokens=24576,
                max_retries=2,
                on_progress=progress,
                cancelled=cancelled,
            )
        self.assertEqual(len(backend.contexts), 1)

    def test_connection_test_streams_and_uses_configured_timeout_without_saving(self):
        models = ModelSettings(MonitoringAgent(self.catalog), path=self.root / "model.json")
        body = ModelSettingsInput(model="test", base_url="http://127.0.0.1:8080/v1", timeout_sec=90)
        progress = []
        with patch(
            "shopagent_monitor.app.model_settings.create_model_backend",
            return_value=FakeStreamingBackend([events(result())]),
        ) as factory:
            response = models.test(body, on_progress=progress.append)
        self.assertTrue(response["ok"])
        self.assertEqual(factory.call_args.args[0].timeout_sec, 90)
        self.assertEqual(factory.call_args.args[0].max_retries, 0)
        self.assertIn("model_stream", [p["stage"] for p in progress])
        self.assertFalse((self.root / "model.json").exists())

    def test_domain_tool_waits_for_response_completion_even_after_tool_end(self):
        entered, release = threading.Event(), threading.Event()

        def waiting():
            yield ModelStreamEvent(type="toolcall_end", tool_call=result("search", {"query": "耳机"}).tool_call)
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test gate timed out")
            yield ModelStreamEvent(type="done", response=result("search", {"query": "耳机"}))

        backend = FakeStreamingBackend([waiting(), events(result("finish", {"candidates": []}))])
        agent = MonitoringAgent(self.catalog, backend=backend)
        responses = []
        with patch.object(self.catalog, "search", wraps=self.catalog.search) as search:
            worker = threading.Thread(target=lambda: responses.append(agent.search("耳机")))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                search.assert_not_called()
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(search.call_count, 1)
        self.assertEqual(responses[0]["engine"], "model")

    def test_streaming_test_http_endpoint_has_one_terminal_result_and_no_secret_text(self):
        store = MonitorStore(self.root / "monitor.sqlite3")
        service = MonitoringService(store, self.catalog)
        app = create_app(service=service, agent=MonitoringAgent(self.catalog), scheduler_enabled=False)
        backend = FakeStreamingBackend([events(result())])
        with (
            patch("shopagent_monitor.app.model_settings.create_model_backend", return_value=backend),
            TestClient(app) as client,
        ):
            response = client.post(
                "/api/model-settings/test/stream", json={"model": "test", "base_url": "http://127.0.0.1:8080/v1"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/x-ndjson", response.headers["content-type"])
        received = [json.loads(line) for line in response.text.splitlines()]
        self.assertTrue(received[-1]["result"]["ok"])
        self.assertEqual(sum(e["type"] == "result" for e in received), 1)
        self.assertNotIn("private reasoning", response.text)
        self.assertNotIn("fixture-secret", response.text)


class ResponsesCompletionTests(unittest.TestCase):
    def test_incomplete_and_malformed_completed_arguments_never_become_executable(self):
        for finish in (
            {
                "type": "response.incomplete",
                "response": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
            },
            {"type": "response.function_call_arguments.done", "output_index": 0, "arguments": '{"ok":tru'},
            {"type": "response.function_call_arguments.done", "output_index": 0, "arguments": "true"},
        ):

            class Response:
                def __iter__(self):
                    for event in [
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": {
                                "type": "function_call",
                                "name": "connection_check",
                                "call_id": "c",
                                "arguments": "",
                            },
                        },
                        {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"ok":tru'},
                        finish,
                    ]:
                        yield ("data: " + json.dumps(event) + "\n\n").encode()

                def close(self):
                    pass

            config = ModelConfig(
                provider="openai-responses", model="test", stream=True, max_retries=0, api_key_required=False
            )
            with (
                self.subTest(finish=finish),
                patch("shopagent_monitor.llm.model.urllib.request.urlopen", return_value=Response()),
            ):
                with self.assertRaises(ModelResponseError):
                    OpenAIResponsesBackend(config).generate(
                        context=ModelContext(system_prompt="test"), max_output_tokens=128
                    )


class StreamBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_progress_arrives_before_completed_test(self):
        gate = threading.Event()

        def operation(publish, cancelled):
            publish({"type": "progress", "message": "connected"})
            gate.wait(3)
            return {"ok": True}

        stream = operation_events(operation)
        try:
            first = await asyncio.wait_for(anext(stream), 1)
            self.assertEqual(first["message"], "connected")
            self.assertFalse(gate.is_set())
            gate.set()
            rest = [e async for e in stream]
            self.assertEqual(rest, [{"type": "result", "result": {"ok": True}}])
        finally:
            gate.set()
            await stream.aclose()


if __name__ == "__main__":
    unittest.main()
