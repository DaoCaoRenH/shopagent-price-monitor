"""Validated, immutable budgets for monitoring discovery requests."""

from pydantic import BaseModel, ConfigDict, Field


class SearchLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_searches: int = Field(default=2, ge=1, le=20, strict=True)
    max_inspections: int = Field(default=3, ge=0, le=30, strict=True)
    max_model_rounds: int = Field(default=7, ge=2, le=50, strict=True)
