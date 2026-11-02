"""Deterministic monitoring; LLMs never invent or judge observed prices."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from .catalog import MonitoringCatalog
from .domain import MonitorError, PriceProvider, PriceQuote, parse_timestamp, price_minor, utc_now
from .store import MonitorStore
from .simulation import normalize_config
from .advice import build_evidence


class SnapshotPriceProvider:
    def __init__(self, store: MonitorStore):
        self.store = store

    def fetch(self, watch: dict[str, Any], *, now: datetime) -> PriceQuote:
        # Polling a static catalog is not a new market observation.
        return self.store.latest_quote(watch["id"])


class SimulatedPriceProvider:
    def __init__(self, store: MonitorStore):
        self.store = store

    def fetch(self, watch: dict[str, Any], *, now: datetime) -> PriceQuote:
        return self.store.simulation_quote(watch["simulation_run_id"], now)


class MonitoringService:
    def __init__(
        self,
        catalog: MonitoringCatalog,
        store: MonitorStore,
        *,
        clock: Callable[[], datetime] = utc_now,
        providers: dict[str, PriceProvider] | None = None,
    ):
        self.catalog, self.store, self.clock = catalog, store, clock
        self.providers = providers or {
            "snapshot": SnapshotPriceProvider(store),
            "simulation": SimulatedPriceProvider(store),
        }

    def add(
        self,
        asin: str,
        selections: dict[str, str],
        *,
        request: str,
        mode: str = "snapshot",
        interval: int = 3600,
        simulation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mode not in self.providers:
            raise MonitorError("不支持的价格来源")
        if not 30 <= interval <= 604800:
            raise MonitorError("更新间隔应为 30 秒到 7 天")
        if mode != "simulation" and simulation is not None:
            raise MonitorError("快照监控不使用模拟配置")
        config = normalize_config(simulation) if mode == "simulation" else None
        if config and config["engine"] == "replay" and interval > config["tick_seconds"]:
            raise MonitorError("固定回放的检查间隔不能大于模拟时间步")
        saved, amount = self.catalog.resolve_variant(asin, selections)
        now = self.clock()
        watch_id, created = self.store.create(
            self.catalog.product(asin),
            saved,
            request=request,
            mode=mode,
            interval=interval,
            quote=PriceQuote(amount, now, "catalog" if mode == "snapshot" else "simulation"),
            now=now,
            simulation_config=config,
        )
        return {"watch": self.store.get(watch_id), "created": created}

    def restart_replay(self, watch_id: str) -> dict[str, Any]:
        watch = self.store.get(watch_id)
        info = watch.get("simulation")
        if not info or info["engine"] != "replay":
            raise MonitorError("只有固定场景支持重新回放")
        selections, amount = self.catalog.resolve_variant(watch["asin"], watch["selections"])
        config = {key: info[key] for key in ("engine", "scenario", "seed", "tick_seconds")}
        now = self.clock()
        new_id, _ = self.store.create(
            self.catalog.product(watch["asin"]),
            selections,
            request=watch["request"],
            mode="simulation",
            interval=watch["interval_seconds"],
            quote=PriceQuote(amount, now, "scenario_replay"),
            now=now,
            simulation_config=config,
            fresh_replay=True,
            pause_watch_id=watch_id,
        )
        return {"watch": self.store.get(new_id), "created": True}

    def advice_evidence(self, watch_id: str, *, budget: Any = None, urgency: str = "flexible") -> dict[str, Any]:
        return build_evidence(self.store.advice_snapshot(watch_id), self.clock(), budget=budget, urgency=urgency)

    @staticmethod
    def _next_check(watch: dict[str, Any], now: datetime) -> datetime | None:
        if not watch.get("simulation"):
            return None
        epoch = parse_timestamp(watch["simulation"]["epoch"])
        interval = timedelta(seconds=watch["interval_seconds"])
        return epoch + (max(0, (now - epoch) // interval) + 1) * interval

    def refresh(self, watch_id: str, *, force: bool = True) -> dict[str, Any]:
        now = self.clock()
        token = self.store.claim(watch_id, now, force=force)
        if token is None:
            return {"status": "skipped", "watch_id": watch_id}
        watch = {}
        try:
            watch = self.store.get(watch_id)
            quote = self.providers[watch["mode"]].fetch(watch, now=now)
            quote.validate(self.clock())
            info = watch.get("simulation")
            complete = bool(
                info
                and info["engine"] == "replay"
                and quote.simulation_tick is not None
                and quote.simulation_tick >= info["total_steps"] - 1
            )
            result = self.store.finish_check(
                watch_id,
                token,
                self.clock(),
                quote=quote,
                next_check_at=self._next_check(watch, self.clock()),
                complete=complete,
            )
            return {"status": "ok", **result, "watch_id": watch_id}
        except Exception as exc:
            error = str(exc) if isinstance(exc, MonitorError) else f"价格获取失败（{type(exc).__name__}）"
            try:
                self.store.finish_check(
                    watch_id, token, self.clock(), error=error, next_check_at=self._next_check(watch, self.clock())
                )
            except MonitorError:
                pass  # The user may delete a watch while the provider is running.
            return {"status": "error", "error": error, "watch_id": watch_id}

    def run_due(self) -> list[dict[str, Any]]:
        result = []
        for watch_id in self.store.due_ids(self.clock()):
            try:
                result.append(self.refresh(watch_id, force=False))
            except MonitorError:
                continue  # Pause/delete can race with the due list; the next poll is independent.
        return result

    def simulate(self, watch_id: str, value: Any | None = None) -> dict[str, Any]:
        watch = self.store.get(watch_id)
        if watch["mode"] != "simulation":
            raise MonitorError("模拟更新仅适用于模拟监控，不会改变快照监控")
        if value is None:
            return self.refresh(watch_id)
        quote = PriceQuote(price_minor(value), self.clock(), "simulation")
        return self.store.import_quotes([(watch_id, quote)], self.clock())
