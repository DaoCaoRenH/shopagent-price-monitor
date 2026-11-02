"""Transactional SQLite history, durable alerts, and cross-process check leases."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from .domain import MonitorError, PriceQuote, money, parse_timestamp, timestamp, utc_now
from . import simulation


SCHEMA = """
CREATE TABLE IF NOT EXISTS simulation_runs (
    id TEXT PRIMARY KEY, config TEXT NOT NULL, epoch TEXT NOT NULL,
    baseline_minor INTEGER NOT NULL, state TEXT NOT NULL, version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watches (
    id TEXT PRIMARY KEY, asin TEXT NOT NULL, title TEXT NOT NULL, shop TEXT,
    category TEXT, request TEXT NOT NULL, selections TEXT NOT NULL,
    variant_key TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('snapshot','simulation')),
    interval_seconds INTEGER NOT NULL CHECK(interval_seconds >= 30),
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
    next_check_at TEXT NOT NULL, last_checked_at TEXT, last_error TEXT,
    lease_until TEXT, lease_token TEXT, baseline_minor INTEGER NOT NULL,
    simulation_run_id TEXT REFERENCES simulation_runs(id),
    UNIQUE(asin, variant_key, mode)
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id TEXT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    observed_at TEXT NOT NULL, received_at TEXT NOT NULL, source TEXT NOT NULL,
    event TEXT, simulation_tick INTEGER,
    UNIQUE(watch_id, observed_at)
);
CREATE INDEX IF NOT EXISTS observations_watch_time ON observations(watch_id, observed_at);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id TEXT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id) ON DELETE CASCADE,
    previous_low_minor INTEGER NOT NULL, amount_minor INTEGER NOT NULL,
    observed_at TEXT NOT NULL, created_at TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS search_history (
    id TEXT PRIMARY KEY, description TEXT NOT NULL,
    started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
    elapsed_ms INTEGER NOT NULL, engine TEXT NOT NULL,
    result_count INTEGER NOT NULL, model_revision TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
"""


class MonitorStore:
    def __init__(self, path: str | Path, *, migration_now: datetime | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            for table, columns in {
                "watches": {"simulation_run_id": "TEXT REFERENCES simulation_runs(id)"},
                "observations": {"event": "TEXT", "simulation_tick": "INTEGER"},
            }.items():
                existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                for name, definition in columns.items():
                    if name not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            # Upgrade old watches without rewriting their prices, alerts, or baseline.
            now = migration_now or utc_now()
            for watch in db.execute(
                "SELECT * FROM watches WHERE mode='simulation' AND simulation_run_id IS NULL"
            ).fetchall():
                latest = db.execute(
                    "SELECT amount_minor FROM observations WHERE watch_id=? ORDER BY observed_at DESC LIMIT 1",
                    (watch["id"],),
                ).fetchone()
                config = simulation.normalize_config(
                    {"seed": int(hashlib.sha256(watch["id"].encode()).hexdigest()[:8], 16) % 2**31}
                )
                run_id = self._ensure_simulation(
                    db,
                    dict(watch),
                    json.loads(watch["selections"]),
                    config,
                    latest["amount_minor"],
                    now,
                    namespace="upgrade:" + watch["id"],
                )
                db.execute("UPDATE watches SET simulation_run_id=? WHERE id=?", (run_id, watch["id"]))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _require(self, db: sqlite3.Connection, watch_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
        if row is None:
            raise MonitorError("监控不存在", 404)
        return row

    def save_search(
        self,
        description: str,
        result: dict[str, Any],
        *,
        events: list[dict],
        started_at: datetime,
        completed_at: datetime,
        elapsed_ms: int,
        model_revision: str,
        search_limits: dict[str, int],
    ) -> str:
        # Persist only the public result projection, never raw model/provider data.
        product_fields = ("asin", "title", "shop", "category", "price", "option_group_count", "reason")
        event_fields = (
            "sequence",
            "stage",
            "step_id",
            "status",
            "message",
            "elapsed_ms",
            "round",
            "round_limit",
            "engine",
            "count",
        )
        products = [{k: p[k] for k in product_fields if k in p} for p in result["products"]]
        snapshot = {
            "message": result["message"],
            "products": products,
            "events": [{k: event[k] for k in event_fields if k in event} for event in events],
            "search_limits": search_limits,
        }
        if "selection_complete" in result:
            snapshot["selection_complete"] = result["selection_complete"] is True
        if "steps" in result:
            snapshot["steps"] = [
                {k: step[k] for k in ("tool", "query", "count", "asin") if k in step} for step in result["steps"]
            ]
        search_id = uuid4().hex
        with self.transaction() as db:
            db.execute(
                "INSERT INTO search_history "
                "(id,description,started_at,completed_at,elapsed_ms,engine,result_count,model_revision,snapshot) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    search_id,
                    description,
                    timestamp(started_at),
                    timestamp(completed_at),
                    elapsed_ms,
                    result["engine"],
                    len(products),
                    model_revision,
                    json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
                ),
            )
        return search_id

    def list_searches(self, *, query: str = "", limit: int = 20, before: int | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MonitorError("每页记录数量应为 1–100")
        if before is not None and (type(before) is not int or before < 1):
            raise MonitorError("搜索记录分页位置无效")
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with self.transaction() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM search_history WHERE description LIKE ? ESCAPE '\\'", (pattern,)
            ).fetchone()[0]
            rows = db.execute(
                "SELECT rowid AS position,id,description,started_at,completed_at,elapsed_ms,engine,result_count "
                "FROM search_history WHERE description LIKE ? ESCAPE '\\' "
                "AND (? IS NULL OR rowid < ?) ORDER BY rowid DESC LIMIT ?",
                (pattern, before, before, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        records = [dict(row) for row in rows[:limit]]
        cursor = records[-1]["position"] if has_more else None
        for record in records:
            record.pop("position")
        return {"records": records, "total": total, "next_cursor": cursor}

    def get_search(self, search_id: str) -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM search_history WHERE id=?", (search_id,)).fetchone()
        if row is None:
            raise MonitorError("搜索记录不存在", 404)
        record = dict(row)
        snapshot = json.loads(record.pop("snapshot"))
        return {**record, **snapshot}

    def _ensure_simulation(
        self,
        db: sqlite3.Connection,
        product: dict[str, Any],
        selections: dict[str, str],
        config: dict[str, Any],
        base: int,
        now: datetime,
        *,
        namespace: str = "",
    ) -> str:
        identity = {
            "asin": product["asin"],
            "selections": selections,
            "config": config,
            "base": base,
            "version": "price-simulation/1",
            "namespace": namespace,
        }
        run_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        db.execute(
            "INSERT OR IGNORE INTO simulation_runs(id,config,epoch,baseline_minor,state,version) VALUES (?,?,?,?,?,?)",
            (
                run_id,
                json.dumps(config),
                timestamp(now),
                base,
                json.dumps(simulation.initial_state(base)),
                "price-simulation/1",
            ),
        )
        return run_id

    def _advance_simulation(self, db: sqlite3.Connection, run_id: str, now: datetime) -> dict[str, Any]:
        row = db.execute("SELECT * FROM simulation_runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["version"] != "price-simulation/1":
            raise MonitorError("模拟序列版本不可用")
        run = dict(row)
        config = json.loads(run["config"])
        state = json.loads(run["state"])
        target = simulation.tick_at(run["epoch"], now, config["tick_seconds"])
        if target < state["tick"]:
            raise MonitorError("系统时间早于已保存的模拟时间，请检查时钟")
        state = simulation.advance(state, config, run_id, run["baseline_minor"], target)
        run["state"] = json.dumps(state)
        db.execute("UPDATE simulation_runs SET state=? WHERE id=?", (run["state"], run_id))
        return run

    def simulation_quote(self, run_id: str, now: datetime) -> PriceQuote:
        with self.transaction() as db:
            run = self._advance_simulation(db, run_id, now)
        # Failure steps still persist the simulation clock, but never a zero-price sample.
        return simulation.quote_for(run, json.loads(run["state"]))

    def create(
        self,
        product: dict[str, Any],
        selections: dict[str, str],
        *,
        request: str,
        mode: str,
        interval: int,
        quote: PriceQuote,
        now: datetime,
        simulation_config: dict[str, Any] | None = None,
        fresh_replay: bool = False,
        pause_watch_id: str | None = None,
    ) -> tuple[str, bool]:
        quote.validate(now)
        variant_json = json.dumps(selections, ensure_ascii=False, sort_keys=True)
        variant_key = hashlib.sha256(variant_json.encode("utf-8")).hexdigest()
        with self.transaction() as db:
            run_id = None
            if mode == "simulation":
                config = simulation.normalize_config(simulation_config)
                if not fresh_replay:
                    existing_simulation = db.execute(
                        "SELECT w.id FROM watches w JOIN simulation_runs r ON r.id=w.simulation_run_id "
                        "WHERE w.asin=? AND w.selections=? AND r.config=? AND r.version=? "
                        "ORDER BY w.created_at DESC,w.rowid DESC LIMIT 1",
                        (product["asin"], variant_json, json.dumps(config), "price-simulation/1"),
                    ).fetchone()
                    if existing_simulation:
                        return existing_simulation["id"], False
                run_id = self._ensure_simulation(
                    db,
                    product,
                    selections,
                    config,
                    quote.amount_minor,
                    now,
                    namespace=uuid4().hex if config["engine"] == "replay" else "",
                )
                variant_key = hashlib.sha256((variant_json + ":" + run_id).encode()).hexdigest()
            existing = db.execute(
                "SELECT id FROM watches WHERE asin=? AND variant_key=? AND mode=?",
                (product["asin"], variant_key, mode),
            ).fetchone()
            if existing:
                return existing["id"], False
            if run_id:
                run = self._advance_simulation(db, run_id, now)
                quote = simulation.quote_for(run, json.loads(run["state"]))
            if pause_watch_id:
                self._require(db, pause_watch_id)
                db.execute("UPDATE watches SET active=0 WHERE id=?", (pause_watch_id,))
            watch_id = uuid4().hex
            db.execute(
                """INSERT INTO watches
                (id,asin,title,shop,category,request,selections,variant_key,mode,
                 interval_seconds,created_at,next_check_at,last_checked_at,baseline_minor,simulation_run_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    watch_id,
                    product["asin"],
                    product["title"],
                    product.get("shop"),
                    product.get("category"),
                    request,
                    variant_json,
                    variant_key,
                    mode,
                    interval,
                    timestamp(now),
                    timestamp(now + timedelta(seconds=interval)),
                    timestamp(now),
                    quote.amount_minor,
                    run_id,
                ),
            )
            self._record(db, watch_id, quote, now)
            return watch_id, True

    def _record(self, db: sqlite3.Connection, watch_id: str, quote: PriceQuote, now: datetime) -> dict[str, Any]:
        quote.validate(now)
        observed_at = timestamp(quote.observed_at)
        duplicate = db.execute(
            "SELECT amount_minor FROM observations WHERE watch_id=? AND observed_at=?",
            (watch_id, observed_at),
        ).fetchone()
        if duplicate:
            if duplicate["amount_minor"] != quote.amount_minor:
                raise MonitorError("同一观测时间已有不同价格，不能覆盖历史", 409)
            return {"inserted": False, "alert_created": False}
        prior = db.execute(
            "SELECT MIN(amount_minor) AS low, MAX(observed_at) AS latest FROM observations WHERE watch_id=?",
            (watch_id,),
        ).fetchone()
        cursor = db.execute(
            "INSERT INTO observations(watch_id,amount_minor,observed_at,received_at,source,event,simulation_tick) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                watch_id,
                quote.amount_minor,
                observed_at,
                timestamp(now),
                quote.source,
                quote.event,
                quote.simulation_tick,
            ),
        )
        alert = prior["low"] is not None and quote.amount_minor < prior["low"] and observed_at > prior["latest"]
        if alert:
            db.execute(
                """INSERT INTO alerts(watch_id,observation_id,previous_low_minor,
                amount_minor,observed_at,created_at) VALUES (?,?,?,?,?,?)""",
                (watch_id, cursor.lastrowid, prior["low"], quote.amount_minor, observed_at, timestamp(now)),
            )
        return {"inserted": True, "alert_created": bool(alert)}

    def import_quotes(self, entries: list[tuple[str, PriceQuote]], now: datetime) -> dict[str, int]:
        # Sort historical imports chronologically so batch order cannot create false alerts.
        entries = sorted(entries, key=lambda entry: entry[1].observed_at)
        inserted = alerts = 0
        with self.transaction() as db:
            for watch_id, quote in entries:
                watch = self._require(db, watch_id)
                if not watch["active"]:
                    raise MonitorError("请先恢复监控再导入报价")
                expected = "simulation" if watch["mode"] == "simulation" else "import"
                if quote.source != expected:
                    raise MonitorError("报价来源与监控模式不匹配")
                if watch["simulation_run_id"]:
                    run = db.execute(
                        "SELECT config FROM simulation_runs WHERE id=?", (watch["simulation_run_id"],)
                    ).fetchone()
                    if json.loads(run["config"])["engine"] == "replay":
                        raise MonitorError("固定回放不接受手动报价，请新建事件模拟或快照监控")
                if watch["lease_until"] and watch["lease_until"] > timestamp(now):
                    raise MonitorError("商品正在更新，请稍后导入", 409)
                result = self._record(db, watch_id, quote, now)
                inserted += result["inserted"]
                alerts += result["alert_created"]
                db.execute("UPDATE watches SET last_error=NULL WHERE id=?", (watch_id,))
        return {"inserted": inserted, "alerts_created": alerts, "duplicates": len(entries) - inserted}

    def _payload(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["selections"] = json.loads(item["selections"])
        item["active"] = bool(item["active"])
        latest = db.execute(
            "SELECT * FROM observations WHERE watch_id=? ORDER BY observed_at DESC LIMIT 1",
            (item["id"],),
        ).fetchone()
        stats = db.execute(
            "SELECT MIN(amount_minor) AS low, COUNT(*) AS count, MAX(id) AS revision FROM observations WHERE watch_id=?",
            (item["id"],),
        ).fetchone()
        item.update(
            {
                "current_price": money(latest["amount_minor"]),
                "current_minor": latest["amount_minor"],
                "current_observed_at": latest["observed_at"],
                "source": latest["source"],
                "low_price": money(stats["low"]),
                "low_minor": stats["low"],
                "sample_count": stats["count"],
                "history_revision": stats["revision"],
                "baseline_price": money(item["baseline_minor"]),
                "change_percent": round((latest["amount_minor"] / item["baseline_minor"] - 1) * 100, 2),
            }
        )
        run = (
            db.execute("SELECT * FROM simulation_runs WHERE id=?", (item["simulation_run_id"],)).fetchone()
            if item["simulation_run_id"]
            else None
        )
        item["simulation"] = simulation.describe(dict(run)) if run else None
        for key in ("lease_until", "lease_token", "variant_key"):
            item.pop(key, None)
        return item

    def get(self, watch_id: str) -> dict[str, Any]:
        with self.transaction() as db:
            return self._payload(db, self._require(db, watch_id))

    def list(self) -> list[dict[str, Any]]:
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM watches ORDER BY created_at DESC").fetchall()
            return [self._payload(db, row) for row in rows]

    def history(self, watch_id: str) -> list[dict[str, Any]]:
        with self.transaction() as db:
            self._require(db, watch_id)
            rows = db.execute(
                "SELECT * FROM observations WHERE watch_id=? ORDER BY observed_at DESC LIMIT 2000",
                (watch_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "price": money(r["amount_minor"]),
                "amount_minor": r["amount_minor"],
                "observed_at": r["observed_at"],
                "source": r["source"],
                "event": r["event"],
                "simulation_tick": r["simulation_tick"],
            }
            for r in reversed(rows)
        ]

    def advice_snapshot(self, watch_id: str) -> dict[str, Any]:
        """One transaction keeps full-history facts and the bounded recent window consistent."""
        with self.transaction() as db:
            watch = self._payload(db, self._require(db, watch_id))
            rows = db.execute(
                "SELECT id,amount_minor,observed_at FROM observations WHERE watch_id=? "
                "ORDER BY observed_at DESC LIMIT 12",
                (watch_id,),
            ).fetchall()
            prior = db.execute(
                "SELECT MIN(amount_minor) AS low,MIN(observed_at) AS first "
                "FROM observations WHERE watch_id=? AND id<>?",
                (watch_id, rows[0]["id"]),
            ).fetchone()
            return {
                "watch": watch,
                "recent": [dict(row) for row in reversed(rows)],
                "previous_low_minor": prior["low"],
                "first_observed_at": prior["first"] or rows[0]["observed_at"],
            }

    def latest_quote(self, watch_id: str) -> PriceQuote:
        with self.transaction() as db:
            self._require(db, watch_id)
            row = db.execute(
                "SELECT * FROM observations WHERE watch_id=? ORDER BY observed_at DESC LIMIT 1",
                (watch_id,),
            ).fetchone()
        return PriceQuote(
            row["amount_minor"],
            parse_timestamp(row["observed_at"]),
            row["source"],
            event=row["event"],
            simulation_tick=row["simulation_tick"],
        )

    def update(self, watch_id: str, *, active: bool | None, interval: int | None, now: datetime) -> None:
        with self.transaction() as db:
            watch = self._require(db, watch_id)
            period = interval if interval is not None else watch["interval_seconds"]
            if type(period) is not int or not 30 <= period <= 604800:
                raise MonitorError("更新间隔应为 30 秒到 7 天")
            next_check = now + timedelta(seconds=period)
            if watch["simulation_run_id"]:
                run = db.execute(
                    "SELECT config,epoch FROM simulation_runs WHERE id=?", (watch["simulation_run_id"],)
                ).fetchone()
                config = json.loads(run["config"])
                if config["engine"] == "replay" and period > config["tick_seconds"]:
                    raise MonitorError("固定回放的检查间隔不能大于模拟时间步")
                epoch = parse_timestamp(run["epoch"])
                step = timedelta(seconds=period)
                next_check = epoch + (max(0, (now - epoch) // step) + 1) * step
            db.execute(
                "UPDATE watches SET active=?,interval_seconds=?,next_check_at=? WHERE id=?",
                (int(active if active is not None else watch["active"]), period, timestamp(next_check), watch_id),
            )

    def delete(self, watch_id: str) -> None:
        with self.transaction() as db:
            self._require(db, watch_id)
            db.execute("DELETE FROM watches WHERE id=?", (watch_id,))

    def due_ids(self, now: datetime) -> list[str]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT id FROM watches WHERE active=1 AND next_check_at<=? "
                "AND (lease_until IS NULL OR lease_until<=?) ORDER BY next_check_at LIMIT 100",
                (timestamp(now), timestamp(now)),
            ).fetchall()
        return [row["id"] for row in rows]

    def claim(self, watch_id: str, now: datetime, *, force: bool) -> str | None:
        with self.transaction() as db:
            watch = self._require(db, watch_id)
            if not watch["active"]:
                raise MonitorError("监控已暂停，请先恢复")
            if watch["lease_until"] and watch["lease_until"] > timestamp(now):
                return None
            if not force and watch["next_check_at"] > timestamp(now):
                return None
            token = uuid4().hex
            db.execute(
                "UPDATE watches SET lease_token=?,lease_until=? WHERE id=?",
                (token, timestamp(now + timedelta(seconds=120)), watch_id),
            )
            return token

    def finish_check(
        self,
        watch_id: str,
        token: str,
        now: datetime,
        *,
        quote: PriceQuote | None = None,
        error: str | None = None,
        next_check_at: datetime | None = None,
        complete: bool = False,
    ) -> dict[str, Any]:
        with self.transaction() as db:
            watch = self._require(db, watch_id)
            if watch["lease_token"] != token:
                raise MonitorError("检查租约已被更新，请重试", 409)
            result = {"inserted": False, "alert_created": False}
            if quote is not None and watch["active"]:
                result = self._record(db, watch_id, quote, now)
            db.execute(
                """UPDATE watches SET lease_token=NULL,lease_until=NULL,last_checked_at=?,
                next_check_at=?,last_error=?,active=CASE WHEN ? THEN 0 ELSE active END WHERE id=?""",
                (
                    timestamp(now),
                    timestamp(next_check_at or now + timedelta(seconds=watch["interval_seconds"])),
                    error,
                    int(complete),
                    watch_id,
                ),
            )
            return result

    def alerts(self) -> list[dict[str, Any]]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT a.*,w.title,w.mode,w.selections FROM alerts a JOIN watches w "
                "ON w.id=a.watch_id ORDER BY a.created_at DESC,a.id DESC LIMIT 200",
            ).fetchall()
        return [
            {
                **dict(r),
                "is_read": bool(r["is_read"]),
                "selections": json.loads(r["selections"]),
                "price": money(r["amount_minor"]),
                "previous_low": money(r["previous_low_minor"]),
                "drop_percent": round((1 - r["amount_minor"] / r["previous_low_minor"]) * 100, 2),
            }
            for r in rows
        ]

    def read_alert(self, alert_id: int) -> None:
        with self.transaction() as db:
            if db.execute("UPDATE alerts SET is_read=1 WHERE id=?", (alert_id,)).rowcount == 0:
                raise MonitorError("提醒不存在", 404)

    def stats(self) -> dict[str, int]:
        with self.transaction() as db:
            return {
                "watch_count": db.execute("SELECT COUNT(*) FROM watches").fetchone()[0],
                "active_count": db.execute("SELECT COUNT(*) FROM watches WHERE active=1").fetchone()[0],
                "observation_count": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
                "unread_count": db.execute("SELECT COUNT(*) FROM alerts WHERE is_read=0").fetchone()[0],
            }
