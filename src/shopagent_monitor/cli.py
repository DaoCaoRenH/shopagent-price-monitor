"""Command-line entry point for local price monitoring."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .paths import DEFAULT_DATASET_PATH, default_state_dir


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="ShopAgent 商品搜索与价格监控")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=8090)
    result.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET_PATH, help="公开商品目录 JSON；默认使用随包提供的虚构演示商品"
    )
    result.add_argument(
        "--data-dir",
        type=Path,
        default=default_state_dir(),
        help="数据库与本机模型配置目录，默认 .shopagent/ 或 SHOPAGENT_DATA_DIR",
    )
    result.add_argument("--db", type=Path, help="覆盖 SQLite 数据库位置")
    result.add_argument("--model-config", type=Path, help="首次启用模型时使用的配置 JSON")
    result.add_argument("--model-settings", type=Path, help="覆盖本机持久化模型设置位置")
    result.add_argument("--catalog-only", action="store_true", help="本次启动关闭模型，可在页面重新启用")
    result.add_argument("--poll-seconds", type=float, default=5)
    result.add_argument("--no-scheduler", action="store_true")
    return result


def main(argv: list[str] | None = None) -> None:
    options = parser()
    args = options.parse_args(argv)
    if not 1 <= args.port <= 65535:
        options.error("port must be between 1 and 65535")
    if args.poll_seconds <= 0:
        options.error("poll-seconds must be positive")
    if not args.dataset.is_file():
        options.error("dataset file does not exist")
    data_dir = args.data_dir.expanduser().resolve()
    from .app.web import create_app
    import uvicorn

    app = create_app(
        dataset=args.dataset,
        db_path=args.db or data_dir / "monitor.sqlite3",
        model_config=args.model_config,
        model_settings_path=args.model_settings or data_dir / "secrets/model.json",
        start_catalog_only=args.catalog_only,
        scheduler_enabled=not args.no_scheduler,
        poll_seconds=args.poll_seconds,
    )
    uvicorn.run(app, host=args.host, port=args.port)
