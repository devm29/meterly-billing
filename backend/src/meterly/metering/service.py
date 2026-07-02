from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.errors import ConflictError, InvalidRequestError, NotFoundError
from meterly.ingestion.backfill import backfill_metric
from meterly.log import get_logger
from meterly.metering.definitions import Aggregation, Metric, MetricDefinition, parse_group_key
from meterly.metering.locks import lock_metric_definitions
from meterly.metering.repository import Granularity, MetricRepository, UsageRepository

log = get_logger(__name__)
MAX_RECONCILE_SPAN = timedelta(days=400)


class SeriesPoint(BaseModel):
    t: datetime
    values: dict[str, Decimal]


class UsageSeries(BaseModel):
    metric: Metric
    granularity: Granularity
    start: datetime
    end: datetime
    series: list[str]
    points: list[SeriesPoint]
    total: Decimal


class Reconciliation(BaseModel):
    metric_code: str
    customer_id: UUID
    start: datetime
    end: datetime
    from_rollups: Decimal
    from_raw_events: Decimal
    matches: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def series_label(group_key: str) -> str:
    dims = parse_group_key(group_key)
    if not dims:
        return "total"
    return " · ".join(v if v is not None else "(none)" for v in dims.values())


class MeteringService:
    def __init__(self, session: AsyncSession, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock
        self._metrics = MetricRepository(session)
        self._usage = UsageRepository(session)

    async def metrics(self) -> list[Metric]:
        return await self._metrics.all()

    async def create(self, definition: MetricDefinition) -> Metric:
        """Create a metric and fold the existing event log into its rollups atomically.

        Ingestion pauses for the duration (it waits on the metric lock), which keeps the
        backfill exact; fine for metric creation, which is rare and operator-driven.
        """
        try:
            await lock_metric_definitions(self._session)
            metric = await self._metrics.create(definition)
            backfill = await backfill_metric(self._session, metric)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(f"metric {definition.code!r} already exists") from exc
        log.info(
            "metric.created",
            code=metric.code,
            backfilled_events=backfill.events,
            unreadable_events=backfill.skipped,
        )
        return metric

    async def require(self, code: str) -> Metric:
        metric = await self._metrics.get_by_code(code)
        if metric is None:
            raise NotFoundError(f"metric {code!r} does not exist")
        return metric

    async def series(
        self,
        code: str,
        *,
        days: int,
        granularity: Granularity,
        customer_id: UUID | None = None,
        by_group: bool = False,
    ) -> UsageSeries:
        metric = await self.require(code)
        step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
        now = self._clock().astimezone(UTC)
        if granularity == "hour":
            end = now.replace(minute=0, second=0, microsecond=0) + step
        else:
            end = now.replace(hour=0, minute=0, second=0, microsecond=0) + step
        start = end - timedelta(days=days)
        rows = await self._usage.series(
            metric, start, end, granularity, customer_id=customer_id, by_group=by_group
        )

        by_bucket: dict[datetime, dict[str, Decimal]] = {}
        for bucket, key, value in rows:
            by_bucket.setdefault(bucket, {})[series_label(key)] = value
        label_totals = _label_totals(metric.aggregation, rows)
        labels = sorted(label_totals, key=lambda name: (-label_totals[name], name))

        points: list[SeriesPoint] = []
        carry = {label: Decimal(0) for label in labels}
        cursor = start
        while cursor < end:
            seen = by_bucket.get(cursor, {})
            if metric.aggregation is Aggregation.LATEST:
                carry.update(seen)
                values = dict(carry)
            else:
                values = {label: seen.get(label, Decimal(0)) for label in labels}
            points.append(SeriesPoint(t=cursor, values=values))
            cursor += step

        match metric.aggregation:
            case Aggregation.UNIQUE_COUNT:
                total = await self._usage.distinct_total(metric, start, end, customer_id)
            case Aggregation.MAX:
                total = max(label_totals.values(), default=Decimal(0))
            case _:
                # COUNT and SUM add up; for LATEST the label totals are each group's last value.
                total = sum(label_totals.values(), Decimal(0))
        return UsageSeries(
            metric=metric,
            granularity=granularity,
            start=start,
            end=end,
            series=labels,
            points=points,
            total=total,
        )

    async def reconcile(
        self, code: str, customer_id: UUID, start: datetime, end: datetime
    ) -> Reconciliation:
        if start.tzinfo is None or end.tzinfo is None:
            raise InvalidRequestError("start and end need a UTC offset")
        if start >= end:
            raise InvalidRequestError("start must be before end")
        if end - start > MAX_RECONCILE_SPAN:
            raise InvalidRequestError(f"reconcile at most {MAX_RECONCILE_SPAN.days} days at once")
        if any(t.minute or t.second or t.microsecond for t in (start, end)):
            # Rollups are hourly, so any other boundary would report a false mismatch.
            raise InvalidRequestError("start and end must fall on the hour")
        metric = await self.require(code)
        rolled = (await self._usage.usage(metric, customer_id, start, end)).total
        raw = await self._usage.raw_total(metric, customer_id, start, end)
        return Reconciliation(
            metric_code=code,
            customer_id=customer_id,
            start=start,
            end=end,
            from_rollups=rolled,
            from_raw_events=raw,
            matches=rolled == raw,
        )


def _label_totals(
    aggregation: Aggregation, rows: list[tuple[datetime, str, Decimal]]
) -> dict[str, Decimal]:
    """Per-series total over the window, combined the way the aggregation combines."""
    totals: dict[str, Decimal] = {}
    for _, key, value in sorted(rows, key=lambda row: row[0]):
        label = series_label(key)
        previous = totals.get(label)
        match aggregation:
            case Aggregation.MAX:
                totals[label] = value if previous is None else max(previous, value)
            case Aggregation.LATEST:
                totals[label] = value
            case _:
                totals[label] = (previous or Decimal(0)) + value
    return totals
