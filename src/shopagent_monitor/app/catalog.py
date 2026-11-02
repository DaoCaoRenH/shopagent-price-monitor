"""Answer-free public catalog projection and exact-option price resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..catalog_retrieval import CatalogRetriever, CatalogRetrieverConfig, catalog_documents_from_items
from ..data import load_catalog
from ..paths import DEFAULT_DATASET_PATH, DEFAULT_CATALOG_RETRIEVER_CONFIG_PATH
from .domain import MonitorError, money, price_minor


class MonitoringCatalog:
    def __init__(self, dataset: str | Path = DEFAULT_DATASET_PATH):
        self.is_demo = Path(dataset).resolve() == DEFAULT_DATASET_PATH.resolve()
        items = load_catalog(dataset)
        self.items = {item.candidate.asin: item for item in items}
        config = CatalogRetrieverConfig.from_file(DEFAULT_CATALOG_RETRIEVER_CONFIG_PATH)
        self.retriever = CatalogRetriever(
            catalog_documents_from_items(items),
            {key: item.candidate for key, item in self.items.items()},
            config,
        )

    def product(self, asin: str, *, detail: bool = False) -> dict[str, Any]:
        item = self.items.get(asin)
        if item is None:
            raise MonitorError("商品不存在", 404)
        result: dict[str, Any] = {
            "asin": asin,
            "title": item.candidate.title,
            "shop": item.candidate.shop,
            "category": item.candidate.category,
            "price": item.candidate.price,
            "option_group_count": len(item.options),
        }
        if detail:
            # Never send is_selected, instructions, persona, or evaluator fields.
            result.update(
                {
                    "description": item.description[:4000],
                    "attributes": list(item.attributes),
                    "option_groups": {
                        group: [
                            {
                                "value": str(v.get("value", "")),
                                "available": v.get("is_available") is not False,
                                "price": v.get("price"),
                            }
                            for v in values
                            if str(v.get("value", "")).strip()
                        ]
                        for group, values in item.options.items()
                    },
                }
            )
        return result

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [self.product(c.asin) for c in self.retriever.search(query).candidates[:limit]]

    def resolve_variant(self, asin: str, selections: dict[str, str]) -> tuple[dict[str, str], int]:
        item = self.items.get(asin)
        if item is None:
            raise MonitorError("商品不存在", 404)
        groups = item.options
        if set(selections) - set(groups):
            raise MonitorError("规格组不属于当前商品，请重新选择")
        saved: dict[str, str] = {}
        selected_prices: set[int] = set()
        for group, values in groups.items():
            available = [v for v in values if v.get("is_available") is not False and str(v.get("value", "")).strip()]
            choice = selections.get(group)
            if choice is None and len(available) == 1:
                choice = str(available[0]["value"])
            matching = [v for v in available if str(v.get("value")) == choice]
            if len(matching) != 1:
                raise MonitorError(f"请选择当前商品的可用规格：{group}")
            saved[group] = str(choice)
            if matching[0].get("price") is not None:
                selected_prices.add(price_minor(matching[0]["price"]))
        if len(selected_prices) == 1:
            return saved, next(iter(selected_prices))
        if len(selected_prices) > 1:
            raise MonitorError("所选规格的公开价格不一致，无法确定组合总价")
        base_prices = {price_minor(value) for value in item.public_prices}
        if len(base_prices) != 1:
            raise MonitorError("商品只有价格区间，尚无所选规格的明确报价")
        return saved, next(iter(base_prices))

    def preview_variant(self, asin: str, selections: dict[str, str]) -> dict[str, Any]:
        saved, amount = self.resolve_variant(asin, selections)
        return {"selections": saved, "price": money(amount)}
