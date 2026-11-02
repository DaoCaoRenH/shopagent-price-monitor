"""Read public product catalogs; task labels and evaluator answers are not loaded."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .contracts import ProductCandidate
from .catalog_retrieval import sanitize_catalog_record
from .paths import DEFAULT_DATASET_PATH


@dataclass(frozen=True)
class CatalogItem:
    candidate: ProductCandidate
    attributes: tuple[str, ...]
    description: str
    options: dict[str, tuple[dict[str, Any], ...]]
    subtitle: str = ""
    public_prices: tuple[float, ...] = ()
    price_coverage_complete: bool = False


def load_catalog(path: str | Path = DEFAULT_DATASET_PATH) -> tuple[CatalogItem, ...]:
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("dataset root must be a JSON list")
    items: list[CatalogItem] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        asin = str(record.get("asin", "")).strip()
        title = str(record.get("title", "")).strip()
        if not asin or not title:
            continue
        if asin in seen:
            raise ValueError(f"duplicate product ID: {asin}")
        seen.add(asin)
        document = sanitize_catalog_record(record)
        pricing = record.get("pricing") or []
        price = _first_float(pricing)
        options: dict[str, tuple[dict[str, Any], ...]] = {}
        raw_options = record.get("customization_options")
        if isinstance(raw_options, dict):
            for group, values in raw_options.items():
                if isinstance(values, list):
                    options[str(group)] = tuple(
                        {key: value[key] for key in ("value", "is_available", "price") if key in value}
                        for value in values
                        if isinstance(value, dict)
                    )
        items.append(
            CatalogItem(
                candidate=ProductCandidate(
                    rank=None,
                    asin=asin,
                    title=title,
                    price=price,
                    price_text=str(price) if price is not None else None,
                    category=str(record.get("category", "")),
                    shop=str(record.get("shop_name", "")),
                    visible_fields=("asin", "title", "price", "category"),
                ),
                attributes=tuple(str(value) for value in (record.get("attribute") or []) if value is not None),
                description=str(record.get("full_description", "")),
                options=options,
                subtitle=str(record.get("sub_title", "")),
                public_prices=document.public_prices,
                price_coverage_complete=document.price_coverage_complete,
            )
        )
    return tuple(items)


def _float_values(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            continue
    return result


def _first_float(value: Any) -> float | None:
    values = _float_values(value)
    return values[0] if values else None
