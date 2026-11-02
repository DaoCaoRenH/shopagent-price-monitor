"""Public product fields shared by catalog loading and retrieval."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int | None = Field(default=None, ge=1)
    asin: str = Field(min_length=1)
    title: str = ""
    price_text: str | None = None
    visible_fields: tuple[str, ...] = ()
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    category: str | None = None
    shop: str | None = None

    @field_validator("asin", "title", "price_text", "category", "shop", mode="before")
    @classmethod
    def normalize_strings(cls, value: Any) -> Any:
        return None if value is None else str(value).strip()
