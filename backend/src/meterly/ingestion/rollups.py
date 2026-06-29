from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from meterly.metering.definitions import Reading

type RollupKey = tuple[UUID, UUID, datetime, str]


@dataclass(slots=True)
class RollupDelta:
    event_count: int = 0
    sum_value: Decimal = Decimal(0)
    max_value: Decimal | None = None
    latest_value: Decimal | None = None
    latest_at: datetime | None = None
    distinct: set[str] = field(default_factory=set)

    def add(self, reading: Reading, at: datetime) -> None:
        self.event_count += 1
        if reading.distinct is not None:
            self.distinct.add(reading.distinct)
        value = reading.numeric
        if value is None:
            return
        self.sum_value += value
        self.max_value = value if self.max_value is None else max(self.max_value, value)
        if self.latest_at is None or at >= self.latest_at:
            self.latest_at, self.latest_value = at, value


def hour_bucket(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def accumulate(
    deltas: dict[RollupKey, RollupDelta], customer_id: UUID, at: datetime, reading: Reading
) -> None:
    key = (customer_id, reading.metric_id, hour_bucket(at), reading.group_key)
    deltas.setdefault(key, RollupDelta()).add(reading, at)


def ordered(deltas: dict[RollupKey, RollupDelta]) -> dict[RollupKey, RollupDelta]:
    """Canonical row order, so concurrent upserts lock rollup rows in the same sequence."""
    return dict(
        sorted(
            deltas.items(),
            key=lambda item: (str(item[0][0]), str(item[0][1]), item[0][2], item[0][3]),
        )
    )


def fold(readings: Iterable[tuple[UUID, datetime, Reading]]) -> dict[RollupKey, RollupDelta]:
    """Pre-aggregate a batch so each rollup row is upserted exactly once per statement."""
    deltas: dict[RollupKey, RollupDelta] = {}
    for customer_id, at, reading in readings:
        accumulate(deltas, customer_id, at, reading)
    return ordered(deltas)
