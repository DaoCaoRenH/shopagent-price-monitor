"""Price and observation semantics shared by providers and storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol


class MonitorError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise MonitorError("观测时间必须包含时区")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise MonitorError("观测时间应为含时区的 ISO 8601 格式") from exc
    if result.tzinfo is None:
        raise MonitorError("观测时间必须包含时区")
    return result.astimezone(timezone.utc)


def price_minor(value: Any) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > Decimal("1000000000"):
            raise ValueError
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise ValueError
        return int(cents)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MonitorError("价格必须大于 0、最多两位小数，且不超过十亿元") from exc


def money(minor: int | None) -> str | None:
    return f"{minor // 100}.{minor % 100:02d}" if minor is not None else None


@dataclass(frozen=True)
class PriceQuote:
    amount_minor: int
    observed_at: datetime
    source: str
    currency: str = "CNY"
    event: str | None = None
    simulation_tick: int | None = None

    def validate(self, now: datetime) -> None:
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise MonitorError("报价金额必须是整数分")
        price_minor(Decimal(self.amount_minor) / 100)
        if self.currency != "CNY":
            raise MonitorError("当前只支持人民币 CNY")
        if self.observed_at.tzinfo is None:
            raise MonitorError("观测时间必须包含时区")
        if self.observed_at > now:
            raise MonitorError("不能导入未来的价格")
        if not self.source or len(self.source) > 80:
            raise MonitorError("报价来源无效")
        if self.event is not None and (not isinstance(self.event, str) or len(self.event) > 160):
            raise MonitorError("价格事件说明无效")
        if self.simulation_tick is not None and (type(self.simulation_tick) is not int or self.simulation_tick < 0):
            raise MonitorError("模拟时间步无效")


class PriceProvider(Protocol):
    """A real platform adapter must return a quote for this exact saved variant.

    Credentials belong in the adapter configuration, never in PriceQuote or logs.
    Unavailable/ambiguous quotes raise errors; they never become a zero price.
    """

    def fetch(self, watch: dict[str, Any], *, now: datetime) -> PriceQuote: ...
