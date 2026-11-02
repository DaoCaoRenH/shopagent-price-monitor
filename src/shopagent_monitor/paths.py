"""Packaged read-only resources and a separate writable application directory."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = PACKAGE_ROOT / "resources/demo-catalog.json"
DEFAULT_CATALOG_RETRIEVER_CONFIG_PATH = PACKAGE_ROOT / "resources/retrieval.json"


def default_state_dir() -> Path:
    return Path(os.environ.get("SHOPAGENT_DATA_DIR", ".shopagent")).expanduser().resolve()
