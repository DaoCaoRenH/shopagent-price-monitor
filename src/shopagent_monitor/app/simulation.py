"""Versioned, deterministic price worlds; polling never advances the clock."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from typing import Any

from .domain import MonitorError, PriceQuote, money, parse_timestamp


MAX_MINOR = 100_000_000_000
EVENT_NAMES = {
    "initial": "初始价格",
    "unchanged": "价格不变",
    "adjustment": "日常调价",
    "promotion_start": "促销开始",
    "promotion_hold": "促销持续",
    "promotion_end": "促销结束，恢复正常售价",
    "rebound": "价格回涨",
    "new_low": "场景降价",
    "unavailable": "模拟报价获取失败",
}
# All prices are relative to the selected variant's starting price, in basis points.
SCENARIOS = {
    "new_lows": {
        "name": "同价、回涨与再次新低",
        "steps": [
            (10000, "initial"),
            (10000, "unchanged"),
            (9500, "new_low"),
            (9500, "unchanged"),
            (10500, "rebound"),
            (9000, "new_low"),
            (9000, "unchanged"),
            (8500, "new_low"),
        ],
    },
    "promotion": {
        "name": "限时促销与恢复原价",
        "steps": [
            (10000, "initial"),
            (10000, "unchanged"),
            (8000, "promotion_start"),
            (8000, "promotion_hold"),
            (10000, "promotion_end"),
            (9000, "promotion_start"),
            (9000, "promotion_hold"),
            (10000, "promotion_end"),
        ],
    },
    "stable": {"name": "持续同价，不应提醒", "steps": [(10000, "initial")] + [(10000, "unchanged")] * 5},
    "continuous_lows": {
        "name": "连续创下新低",
        "steps": [(10000, "initial"), (9800, "new_low"), (9500, "new_low"), (9000, "new_low"), (8500, "new_low")],
    },
    "failure_recovery": {
        "name": "报价失败与恢复",
        "steps": [
            (10000, "initial"),
            (None, "unavailable"),
            (None, "unavailable"),
            (9500, "new_low"),
            (9500, "unchanged"),
            (9000, "new_low"),
        ],
    },
}


def normalize_config(value: dict[str, Any] | None = None) -> dict[str, Any]:
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {"engine", "scenario", "seed", "tick_seconds"}:
        raise MonitorError("模拟配置包含不支持的字段")
    engine, seed, period = value.get("engine", "event"), value.get("seed", 42), value.get("tick_seconds", 30)
    if not isinstance(engine, str) or engine not in {"event", "replay"}:
        raise MonitorError("模拟方式应为 event 或 replay")
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise MonitorError("模拟种子应为 0 到 2147483647 的整数")
    if type(period) is not int or not 30 <= period <= 86400:
        raise MonitorError("模拟时间步应为 30 秒到 24 小时")
    scenario = value.get("scenario")
    if engine == "replay":
        scenario = scenario or "new_lows"
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            raise MonitorError("回放场景不存在")
    elif scenario is not None:
        raise MonitorError("事件模拟不使用固定回放场景")
    return {"engine": engine, "scenario": scenario, "seed": seed, "tick_seconds": period}


def presets() -> dict[str, Any]:
    scenarios = []
    for key, scenario in SCENARIOS.items():
        low = None
        steps = []
        for value, event in scenario["steps"]:
            alert = value is not None and low is not None and value < low
            steps.append(
                {
                    "percent": None if value is None else value / 100,
                    "event": EVENT_NAMES[event],
                    "expected_alert": alert,
                }
            )
            if value is not None:
                low = value if low is None else min(low, value)
        scenarios.append({"id": key, "name": scenario["name"], "steps": steps})
    return {"default": normalize_config(), "version": "price-simulation/1", "scenarios": scenarios}


def scaled(amount: int, basis_points: int) -> int:
    return min(MAX_MINOR, max(1, (amount * basis_points + 5000) // 10000))


def initial_state(base: int) -> dict[str, Any]:
    return {
        "tick": 0,
        "normal_minor": base,
        "amount_minor": base,
        "discount_bps": 0,
        "promotion_until": 0,
        "event": "initial",
        "phase": "normal",
    }


def advance(state: dict[str, Any], config: dict[str, Any], market_key: str, base: int, target: int) -> dict[str, Any]:
    state = dict(state)
    if config["engine"] == "replay":
        steps = SCENARIOS[config["scenario"]]["steps"]
        tick = min(target, len(steps) - 1)
        factor, event = steps[tick]
        state.update(
            tick=tick,
            amount_minor=None if factor is None else scaled(base, factor),
            event=event,
            phase="unavailable" if factor is None else "replay",
        )
        return state
    for tick in range(state["tick"] + 1, target + 1):
        # A separate hash per tick makes the sequence independent of fetch order/retries.
        digest = hashlib.sha256(f"price-simulation/1:{market_key}:{config['seed']}:{tick}".encode()).digest()
        roll = int.from_bytes(digest[:8], "big") % 10000
        if state["discount_bps"]:
            if tick <= state["promotion_until"]:
                state["event"] = "promotion_hold"
            else:
                state.update(discount_bps=0, event="promotion_end")
        elif roll < 8000:
            state["event"] = "unchanged"
        elif roll < 9500:
            delta = int.from_bytes(digest[8:16], "big") % 201 - 100
            normal = scaled(state["normal_minor"], 10000 + delta)
            state.update(normal_minor=max(scaled(base, 9000), min(scaled(base, 11000), normal)), event="adjustment")
        else:
            discount = 1000 + int.from_bytes(digest[8:16], "big") % 1501
            duration = 2 + int.from_bytes(digest[16:24], "big") % 4
            state.update(discount_bps=discount, promotion_until=tick + duration - 1, event="promotion_start")
        state.update(
            tick=tick,
            phase="promotion" if state["discount_bps"] else "normal",
            amount_minor=scaled(state["normal_minor"], 10000 - state["discount_bps"]),
        )
    return state


def tick_at(epoch: str, now: datetime, period: int) -> int:
    return max(0, (now - parse_timestamp(epoch)) // timedelta(seconds=period))


def quote_for(run: dict[str, Any], state: dict[str, Any]) -> PriceQuote:
    config = json.loads(run["config"])
    if state["amount_minor"] is None:
        raise MonitorError(f"固定场景第 {state['tick'] + 1} 步：模拟报价获取失败，将继续尝试后续步骤")
    return PriceQuote(
        state["amount_minor"],
        parse_timestamp(run["epoch"]) + timedelta(seconds=state["tick"] * config["tick_seconds"]),
        "event_simulation" if config["engine"] == "event" else "scenario_replay",
        event=EVENT_NAMES[state["event"]],
        simulation_tick=state["tick"],
    )


def describe(run: dict[str, Any]) -> dict[str, Any]:
    config, state = json.loads(run["config"]), json.loads(run["state"])
    scenario = SCENARIOS.get(config["scenario"])
    return {
        **config,
        "run_id": run["id"],
        "epoch": run["epoch"],
        "version": run["version"],
        "tick": state["tick"],
        "event": EVENT_NAMES[state["event"]],
        "phase": state["phase"],
        "normal_price": money(state["normal_minor"]),
        "base_price": money(run["baseline_minor"]),
        "total_steps": len(scenario["steps"]) if scenario else None,
        "scenario_name": scenario["name"] if scenario else None,
        "complete": bool(scenario and state["tick"] >= len(scenario["steps"]) - 1),
    }
