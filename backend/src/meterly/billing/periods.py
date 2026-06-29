from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum


class Interval(StrEnum):
    MONTH = "month"
    YEAR = "year"

    @property
    def months(self) -> int:
        return 12 if self is Interval.YEAR else 1


@dataclass(frozen=True, slots=True)
class Period:
    """A half-open range of whole UTC days: [start, end)."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"period ends before it starts: {self.start} → {self.end}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def is_empty(self) -> bool:
        return self.days == 0

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=UTC)

    @property
    def ends_at(self) -> datetime:
        return datetime.combine(self.end, time.min, tzinfo=UTC)

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end

    def intersect(self, other: Period) -> Period | None:
        start, end = max(self.start, other.start), min(self.end, other.end)
        return Period(start, end) if start < end else None

    def fraction_of(self, whole: Period) -> Decimal:
        """Day-based proration factor of this window relative to the full billing period."""
        if whole.days == 0:
            return Decimal(0)
        return Decimal(self.days) / Decimal(whole.days)


def add_months(anchor: date, months: int) -> date:
    """Shift by whole months, clamping to month end (Jan 31 + 1 month = Feb 28/29)."""
    index = anchor.year * 12 + anchor.month - 1 + months
    year, month = divmod(index, 12)
    day = min(anchor.day, calendar.monthrange(year, month + 1)[1])
    return date(year, month + 1, day)


def period_containing(anchor: date, interval: Interval, day: date) -> Period:
    """Return the billing period anchored on ``anchor`` that contains ``day``.

    Boundaries are always computed from the original anchor rather than chained, so an
    anchor on the 31st returns to the 31st after passing through a short month.
    """
    step = interval.months
    elapsed = (day.year - anchor.year) * 12 + (day.month - anchor.month)
    k = elapsed // step
    while add_months(anchor, k * step) > day:
        k -= 1
    while add_months(anchor, (k + 1) * step) <= day:
        k += 1
    return Period(add_months(anchor, k * step), add_months(anchor, (k + 1) * step))
