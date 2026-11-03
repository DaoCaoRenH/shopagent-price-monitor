from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

from shopagent_monitor.app.catalog import MonitoringCatalog
from shopagent_monitor.app.web import create_app
from shopagent_monitor.catalog_retrieval import unicode_catalog_terms, sanitize_catalog_record
from shopagent_monitor.cli import parser
from shopagent_monitor.data import load_catalog
from shopagent_monitor.paths import DEFAULT_DATASET_PATH


class PublicPackageTests(unittest.TestCase):
    def test_bundled_demo_products_have_unique_ids_and_resolvable_variants(self):
        catalog = MonitoringCatalog()
        self.assertTrue(catalog.is_demo)
        self.assertEqual(len(catalog.items), 12)
        for asin in catalog.items:
            self.assertTrue(asin.startswith("DEMO-"))
            product = catalog.product(asin, detail=True)
            selected = {
                group: next(v["value"] for v in values if v["available"])
                for group, values in product["option_groups"].items()
            }
            _selections, price = catalog.resolve_variant(asin, selected)
            self.assertGreater(price, 0)
        for request in ("无线降噪耳机", "透气跑步鞋", "不锈钢保温杯"):
            self.assertTrue(catalog.search(request))

    def test_custom_catalog_rejects_duplicates_and_drops_non_public_option_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "custom.json"
            item = {
                "asin": "CUSTOM",
                "title": "杯子",
                "pricing": [30],
                "customization_options": {
                    "颜色": [{"value": "白色", "price": 30, "is_selected": True, "private_field": "fixture"}]
                },
            }
            dataset.write_text(json.dumps([item]), encoding="utf-8")
            catalog = MonitoringCatalog(dataset)
            self.assertFalse(catalog.is_demo)
            self.assertEqual(catalog.items["CUSTOM"].options["颜色"], ({"value": "白色", "price": 30},))
            dataset.write_text(json.dumps([item, item]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate product ID"):
                load_catalog(dataset)

    def test_tokenizer_and_index_only_use_public_product_fields(self):
        self.assertEqual(unicode_catalog_terms("红色/蓝色"), ("红色", "蓝色"))
        document = sanitize_catalog_record(
            {"asin": "A", "title": "公开保温杯", "instructions": ["PRIVATE-FIXTURE"], "target_asin": "PRIVATE-FIXTURE"}
        )
        self.assertNotIn("PRIVATE-FIXTURE", str(document))

    def test_default_app_and_static_assets_work_without_a_model(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(db_path=Path(directory) / "state.sqlite3", scheduler_enabled=False)) as client:
                status = client.get("/api/status").json()
                self.assertTrue(status["catalog_is_demo"])
                self.assertFalse(status["model_enabled"])
                self.assertEqual(status["catalog_count"], 12)
                for path in ("/", "/static/app.js", "/static/style.css"):
                    self.assertEqual(client.get(path).status_code, 200)
                self.assertIn("演示目录", client.get("/").text)
                result = client.post("/api/search", json={"description": "保温杯"}).json()
                self.assertTrue(result["products"])
                self.assertEqual(result["engine"], "catalog")

    def test_cli_resources_are_absolute_and_writable_state_is_separate(self):
        options = parser().parse_args([])
        self.assertEqual(options.dataset, DEFAULT_DATASET_PATH)
        self.assertTrue(options.dataset.is_absolute())
        self.assertIsNone(options.model_config)
        self.assertEqual(options.host, "127.0.0.1")
        self.assertFalse(options.data_dir.is_relative_to(DEFAULT_DATASET_PATH.parent))

    def test_cli_help_and_errors_use_utf8_with_legacy_redirected_streams(self):
        setup = (
            "import sys; "
            "sys.stdout.reconfigure(encoding='cp1252'); "
            "sys.stderr.reconfigure(encoding='cp1252'); "
            "from shopagent_monitor.cli import main; "
        )
        for args, code, stream, expected in (
            (["--help"], 0, "stdout", "商品搜索与价格监控"),
            (["--unknown=测试"], 2, "stderr", "--unknown=测试"),
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, "-c", setup + "main(" + repr(args) + ")"], capture_output=True, check=False
                )
                self.assertEqual(result.returncode, code, result.stderr.decode("utf-8", errors="replace"))
                self.assertIn(expected, getattr(result, stream).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
