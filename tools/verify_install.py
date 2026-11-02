"""Check a built wheel from a temporary working directory, without source paths."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile


PROBE = r"""
from datetime import datetime, timezone
from pathlib import Path
import json
import shopagent_monitor
from shopagent_monitor.paths import DEFAULT_DATASET_PATH
from shopagent_monitor.app.web import create_app
from fastapi.testclient import TestClient

assert Path(shopagent_monitor.__file__).parents[1].name == "site-packages", "expected a wheel installation"
assert DEFAULT_DATASET_PATH.is_file(), "packaged demo catalog is missing"
db = Path.cwd() / "probe.sqlite3"
with TestClient(create_app(db_path=db, scheduler_enabled=False)) as client:
    status = client.get("/api/status").json()
    assert status["catalog_count"] == 12 and status["catalog_is_demo"]
    assert not status["model_enabled"]
    for resource in ("/", "/static/app.js", "/static/style.css", "/docs"):
        assert client.get(resource).status_code == 200, resource
    result = client.post("/api/search", json={"description":"不锈钢保温杯"}).json()
    assert result["products"] and result["search_id"]
    asin = result["products"][0]["asin"]
    product = client.get("/api/products/" + asin).json()
    selections = {group: next(v["value"] for v in options if v["available"])
                  for group, options in product["option_groups"].items()}
    quote = client.post("/api/products/" + asin + "/quote", json={"selections":selections}).json()
    added = client.post("/api/watches", json={"asin":asin, "selections":selections,
                       "request":"演示保温杯", "mode":"snapshot", "interval_seconds":30})
    assert added.status_code == 200, added.text
    watch_id = added.json()["watch"]["id"]
    imported = client.post("/api/prices/import", json={"observations":[{
        "watch_id":watch_id, "price":f"{float(quote['price'])-1:.2f}",
        "observed_at":datetime.now(timezone.utc).isoformat(), "mode":"snapshot"}]})
    assert imported.status_code == 200, imported.text
    assert len(client.get("/api/alerts").json()["alerts"]) == 1
    assert client.post("/api/watches/" + watch_id + "/advice", json={}).status_code == 200
with TestClient(create_app(db_path=db, scheduler_enabled=False)) as client:
    assert len(client.get("/api/watches").json()["watches"]) == 1
    assert client.get("/api/search-history/" + result["search_id"]).json()["products"]
print(json.dumps({"version":shopagent_monitor.__version__, "catalog_count":12,
                  "assets":True, "price_flow":True, "persistence":True}))
"""


def main() -> None:
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "SHOPAGENT_DATA_DIR"}}
    with tempfile.TemporaryDirectory(prefix="shopagent-wheel-") as directory:
        subprocess.run(
            [sys.executable, "-I", "-m", "shopagent_monitor", "--help"],
            cwd=directory,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run([sys.executable, "-I", "-c", PROBE], cwd=directory, env=env, check=True)


if __name__ == "__main__":
    main()
