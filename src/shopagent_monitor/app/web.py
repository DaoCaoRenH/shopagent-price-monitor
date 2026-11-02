"""FastAPI routes and a lifecycle-managed, durable price-check scheduler."""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing, asynccontextmanager, suppress
import logging
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ..paths import DEFAULT_DATASET_PATH, default_state_dir
from ..llm.model import ModelConfig
from .agent import MonitoringAgent
from .catalog import MonitoringCatalog
from .domain import MonitorError, PriceQuote, parse_timestamp, price_minor, timestamp, utc_now
from .service import MonitoringService
from .store import MonitorStore
from .simulation import presets
from .model_settings import ModelSettings, ModelSettingsInput
from .search_progress import search_events, operation_events
from .search_history import SearchRecorder


LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchInput(Input):
    description: str = Field(min_length=1, max_length=500)


class SelectionInput(Input):
    selections: dict[str, str] = Field(default_factory=dict, max_length=20)


class SimulationInput(Input):
    engine: Literal["event", "replay"] = "event"
    scenario: str | None = Field(default=None, max_length=80)
    seed: int = Field(default=42, ge=0, le=2147483647, strict=True)
    tick_seconds: int = Field(default=30, ge=30, le=86400, strict=True)


class WatchInput(SelectionInput):
    asin: str = Field(min_length=1, max_length=80)
    request: str = Field(default="", max_length=500)
    mode: Literal["snapshot", "simulation"] = "snapshot"
    interval_seconds: int = Field(default=3600, ge=30, le=604800, strict=True)
    simulation: SimulationInput | None = None


class WatchUpdate(Input):
    active: bool | None = Field(default=None, strict=True)
    interval_seconds: int | None = Field(default=None, ge=30, le=604800, strict=True)


class SimulateInput(Input):
    price: Any = None


class AdviceInput(Input):
    budget: Any = None
    urgency: Literal["flexible", "soon"] = "flexible"


class ObservationInput(Input):
    watch_id: str = Field(min_length=1, max_length=80)
    price: Any
    observed_at: str = Field(max_length=80)
    currency: Literal["CNY"] = "CNY"
    mode: Literal["snapshot", "simulation"] = "snapshot"


class ImportInput(Input):
    observations: list[ObservationInput] = Field(min_length=1, max_length=1000)


def create_app(
    *,
    dataset: str | Path = DEFAULT_DATASET_PATH,
    db_path: str | Path | None = None,
    model_config: str | Path | None = None,
    service: MonitoringService | None = None,
    agent: MonitoringAgent | None = None,
    model_settings_path: str | Path | None = None,
    start_catalog_only: bool = False,
    scheduler_enabled: bool = True,
    poll_seconds: float = 5,
) -> FastAPI:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")

    async def scheduler(app: FastAPI):
        while True:
            try:
                await asyncio.to_thread(app.state.monitor.run_due)
                app.state.scheduler_last_poll = timestamp(utc_now())
                app.state.scheduler_error = None
            except Exception as exc:
                app.state.scheduler_error = "本轮检查失败，下一轮将重试"
                LOGGER.warning("price scheduler failed: %s", type(exc).__name__)
            await asyncio.sleep(poll_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        monitor = service
        if monitor is None:
            catalog = await asyncio.to_thread(MonitoringCatalog, dataset)
            monitor = MonitoringService(catalog, MonitorStore(db_path or default_state_dir() / "monitor.sqlite3"))
        app.state.monitor = monitor
        initial_agent = agent or MonitoringAgent(
            monitor.catalog,
            ModelConfig.from_file(model_config) if model_config else None,
        )
        app.state.models = ModelSettings(initial_agent, path=model_settings_path, start_disabled=start_catalog_only)
        app.state.scheduler_last_poll = None
        app.state.scheduler_error = None
        task = asyncio.create_task(scheduler(app)) if scheduler_enabled else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="ShopAgent 价格监控", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def local_write_origin(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and (
                urlsplit(origin).netloc != request.headers.get("host")
                or urlsplit(origin).scheme not in {"http", "https"}
            ):
                return JSONResponse({"detail": "不允许跨站修改本机监控"}, status_code=403)
            size = request.headers.get("content-length", "0")
            if not size.isdigit() or int(size) > 1_000_000:
                return JSONResponse({"detail": "请求内容过大"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/model-settings"):
            # Pydantic errors otherwise echo input values, including credentials.
            return JSONResponse({"detail": "模型配置格式不正确，请检查服务地址、必填项和参数范围。"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(MonitorError)
    async def monitor_error(_request: Request, exc: MonitorError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/status")
    def status():
        monitor = app.state.monitor
        return {
            **monitor.store.stats(),
            "catalog_count": len(monitor.catalog.items),
            "catalog_is_demo": monitor.catalog.is_demo,
            "model_enabled": app.state.models.agent.backend is not None,
            "model_revision": app.state.models.public()["revision"],
            "scheduler_enabled": scheduler_enabled,
            "scheduler_last_poll": app.state.scheduler_last_poll,
            "scheduler_error": app.state.scheduler_error,
            "history_scope": "自开始采集以来的历史最低价",
            "currency": "CNY",
        }

    @app.get("/api/model-settings")
    def get_model_settings():
        return app.state.models.public()

    @app.put("/api/model-settings")
    def save_model_settings(body: ModelSettingsInput):
        return app.state.models.save(body)

    @app.post("/api/model-settings/test")
    def test_model_settings(body: ModelSettingsInput):
        return app.state.models.test(body)

    @app.post("/api/model-settings/test/stream")
    async def stream_test_model_settings(body: ModelSettingsInput):
        async def content():
            async with aclosing(
                operation_events(
                    lambda publish, cancelled: app.state.models.test(body, on_progress=publish, cancelled=cancelled),
                    error_message="连接测试未完成，Agent 可能正在处理其他请求，请稍后重试。",
                )
            ) as events:
                async for event in events:
                    yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(
            content(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/search")
    def search(body: SearchInput):
        description = body.description.strip()
        if not description:
            raise MonitorError("请描述需要监控的商品")
        agent, revision = app.state.models.active()
        return SearchRecorder(agent, app.state.monitor.store, revision).search(description)

    @app.post("/api/search/stream")
    async def stream_search(body: SearchInput):
        description = body.description.strip()
        if not description:
            raise MonitorError("请描述需要监控的商品")
        # Pin the active agent for this request even if settings change mid-search.
        current_agent, revision = app.state.models.active()
        recorder = SearchRecorder(current_agent, app.state.monitor.store, revision)

        async def content():
            async with aclosing(search_events(recorder, description)) as events:
                async for event in events:
                    yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(
            content(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/search-history")
    def search_history(
        q: str = Query(default="", max_length=500),
        limit: int = Query(default=20, ge=1, le=100),
        before: int | None = Query(default=None, ge=1),
    ):
        return app.state.monitor.store.list_searches(query=q, limit=limit, before=before)

    @app.get("/api/search-history/{search_id}")
    def search_history_detail(search_id: str):
        return app.state.monitor.store.get_search(search_id)

    @app.get("/api/simulation-presets")
    def simulation_presets():
        return presets()

    @app.get("/api/products/{asin}")
    def product(asin: str):
        return app.state.monitor.catalog.product(asin, detail=True)

    @app.post("/api/products/{asin}/quote")
    def quote(asin: str, body: SelectionInput):
        return app.state.monitor.catalog.preview_variant(asin, body.selections)

    @app.get("/api/watches")
    def watches():
        return {"watches": app.state.monitor.store.list()}

    @app.post("/api/watches")
    def add_watch(body: WatchInput):
        return app.state.monitor.add(
            body.asin,
            body.selections,
            request=body.request,
            mode=body.mode,
            interval=body.interval_seconds,
            simulation=body.simulation.model_dump() if body.simulation else None,
        )

    @app.patch("/api/watches/{watch_id}")
    def update_watch(watch_id: str, body: WatchUpdate):
        app.state.monitor.store.update(
            watch_id, active=body.active, interval=body.interval_seconds, now=app.state.monitor.clock()
        )
        return app.state.monitor.store.get(watch_id)

    @app.delete("/api/watches/{watch_id}")
    def delete_watch(watch_id: str):
        app.state.monitor.store.delete(watch_id)
        return {"deleted": True}

    @app.get("/api/watches/{watch_id}/history")
    def history(watch_id: str):
        store = app.state.monitor.store
        watch = store.get(watch_id)
        return {"watch": watch, "observations": store.history(watch_id), "total": watch["sample_count"], "limit": 2000}

    @app.post("/api/watches/{watch_id}/refresh")
    def refresh(watch_id: str):
        return app.state.monitor.refresh(watch_id)

    @app.post("/api/watches/{watch_id}/advice")
    def purchase_advice(watch_id: str, body: AdviceInput):
        evidence = app.state.monitor.advice_evidence(watch_id, budget=body.budget, urgency=body.urgency)
        models = app.state.models
        # Capture one agent/revision pair, including during a configuration change.
        agent, revision = models.active()
        return {**agent.advisor.advise(evidence), "model_revision": revision}

    @app.post("/api/watches/{watch_id}/simulate")
    def simulate(watch_id: str, body: SimulateInput):
        return app.state.monitor.simulate(watch_id, body.price)

    @app.post("/api/watches/{watch_id}/replay/restart")
    def restart_replay(watch_id: str):
        return app.state.monitor.restart_replay(watch_id)

    @app.post("/api/prices/import")
    def import_prices(body: ImportInput):
        entries = [
            (
                v.watch_id,
                PriceQuote(
                    price_minor(v.price),
                    parse_timestamp(v.observed_at),
                    "simulation" if v.mode == "simulation" else "import",
                    v.currency,
                ),
            )
            for v in body.observations
        ]
        return app.state.monitor.store.import_quotes(entries, app.state.monitor.clock())

    @app.get("/api/alerts")
    def alerts():
        return {"alerts": app.state.monitor.store.alerts()}

    @app.post("/api/alerts/{alert_id}/read")
    def read_alert(alert_id: int):
        app.state.monitor.store.read_alert(alert_id)
        return {"read": True}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
