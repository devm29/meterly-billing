from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, literal_column, select, text, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.db.models import BillableMetric, UsageRollupHourly, UsageUniqueValue
from meterly.metering.definitions import Aggregation, Metric, MetricDefinition, parse_group_key
from meterly.metering.usage import GroupUsage, MetricUsage

Granularity = Literal["hour", "day"]
R = UsageRollupHourly
U = UsageUniqueValue


def to_metric(row: BillableMetric) -> Metric:
    path = row.field_path or []
    return Metric(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        event_code=row.event_code,
        aggregation=Aggregation(row.aggregation),
        field=".".join(str(p) for p in path) or None,
        group_by=[str(g) for g in row.group_by],
        unit=row.unit,
    )


class MetricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> list[Metric]:
        rows = await self._session.scalars(select(BillableMetric).order_by(BillableMetric.code))
        return [to_metric(r) for r in rows]

    async def get_by_code(self, code: str) -> Metric | None:
        row = await self._session.scalar(select(BillableMetric).where(BillableMetric.code == code))
        return to_metric(row) if row else None

    async def by_codes(self, codes: Sequence[str]) -> dict[str, Metric]:
        if not codes:
            return {}
        rows = await self._session.scalars(
            select(BillableMetric).where(BillableMetric.code.in_(codes))
        )
        return {r.code: to_metric(r) for r in rows}

    async def by_event_codes(self, event_codes: Sequence[str]) -> dict[str, list[Metric]]:
        result: dict[str, list[Metric]] = {}
        if not event_codes:
            return result
        rows = await self._session.scalars(
            select(BillableMetric).where(BillableMetric.event_code.in_(set(event_codes)))
        )
        for row in rows:
            result.setdefault(row.event_code, []).append(to_metric(row))
        return result

    async def create(self, definition: MetricDefinition) -> Metric:
        row = BillableMetric(
            code=definition.code,
            name=definition.name,
            description=definition.description,
            event_code=definition.event_code,
            aggregation=definition.aggregation.value,
            field_path=definition.field.split(".") if definition.field else None,
            group_by=list(definition.group_by),
            unit=definition.unit,
        )
        self._session.add(row)
        await self._session.flush()
        return to_metric(row)


class UsageRepository:
    """Aggregations over hourly rollups (fast path) and raw events (audit path)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def usage(
        self, metric: Metric, customer_id: UUID, start: datetime, end: datetime
    ) -> MetricUsage:
        total = await self._total(metric, customer_id, start, end)
        groups: list[GroupUsage] = []
        if metric.group_by:
            groups = await self._groups(metric, customer_id, start, end)
        return MetricUsage(total=total, groups=groups)

    async def _total(
        self, metric: Metric, customer_id: UUID, start: datetime, end: datetime
    ) -> Decimal:
        stmt: Select[Any]
        match metric.aggregation:
            case Aggregation.UNIQUE_COUNT:
                stmt = select(func.count(func.distinct(U.value))).where(
                    *_unique_window(metric.id, customer_id, start, end)
                )
            case Aggregation.LATEST:
                stmt = (
                    select(R.latest_value)
                    .where(*_rollup_window(metric.id, customer_id, start, end))
                    .where(R.latest_at.is_not(None))
                    .order_by(R.latest_at.desc())
                    .limit(1)
                )
            case _:
                stmt = select(_rollup_measure(metric.aggregation)).where(
                    *_rollup_window(metric.id, customer_id, start, end)
                )
        value = await self._session.scalar(stmt)
        return Decimal(value or 0)

    async def _groups(
        self, metric: Metric, customer_id: UUID, start: datetime, end: datetime
    ) -> list[GroupUsage]:
        stmt: Select[Any, Any]
        match metric.aggregation:
            case Aggregation.UNIQUE_COUNT:
                stmt = (
                    select(U.group_key, func.count(func.distinct(U.value)))
                    .where(*_unique_window(metric.id, customer_id, start, end))
                    .group_by(U.group_key)
                )
            case Aggregation.LATEST:
                stmt = (
                    select(R.group_key, R.latest_value)
                    .where(*_rollup_window(metric.id, customer_id, start, end))
                    .where(R.latest_at.is_not(None))
                    .ext(distinct_on(R.group_key))
                    .order_by(R.group_key, R.latest_at.desc())
                )
            case _:
                stmt = (
                    select(R.group_key, _rollup_measure(metric.aggregation))
                    .where(*_rollup_window(metric.id, customer_id, start, end))
                    .group_by(R.group_key)
                )
        rows = (await self._session.execute(stmt)).all()
        groups = [
            GroupUsage(dimensions=parse_group_key(key), quantity=Decimal(value or 0))
            for key, value in rows
        ]
        return sorted(groups, key=lambda g: (-g.quantity, str(g.dimensions)))

    async def series(
        self,
        metric: Metric,
        start: datetime,
        end: datetime,
        granularity: Granularity,
        customer_id: UUID | None = None,
        by_group: bool = False,
    ) -> list[tuple[datetime, str, Decimal]]:
        """Time series as (bucket, group_key, value); group_key is '{}' unless by_group."""
        source = U if metric.aggregation is Aggregation.UNIQUE_COUNT else R
        bucket = func.date_trunc(granularity, source.bucket_start, "UTC").label("bucket")
        key = source.group_key if by_group else literal_column("'{}'")
        filters = [
            source.metric_id == metric.id,
            source.bucket_start >= start,
            source.bucket_start < end,
        ]
        if customer_id is not None:
            filters.append(source.customer_id == customer_id)

        measure: ColumnElement[Any]
        if metric.aggregation is Aggregation.UNIQUE_COUNT:
            measure = _distinct_per_customer()
        elif metric.aggregation is Aggregation.LATEST:
            # Per bucket, the most recent reading across the bucket (and across customers summed).
            inner = (
                select(
                    bucket,
                    key.label("gk"),
                    R.customer_id,
                    R.group_key.label("rk"),
                    R.latest_value,
                )
                .where(*filters, R.latest_at.is_not(None))
                .ext(distinct_on(text("bucket"), R.customer_id, R.group_key))
                .order_by(text("bucket"), R.customer_id, R.group_key, R.latest_at.desc())
                .subquery()
            )
            latest_stmt = (
                select(inner.c.bucket, inner.c.gk, func.sum(inner.c.latest_value))
                .group_by(inner.c.bucket, inner.c.gk)
                .order_by(inner.c.bucket)
            )
            rows = (await self._session.execute(latest_stmt)).all()
            return [(b, str(g), Decimal(v or 0)) for b, g, v in rows]
        else:
            measure = _rollup_measure(metric.aggregation)

        stmt = (
            select(bucket, key, measure)
            .where(*filters)
            .group_by(text("1"), text("2"))
            .order_by(text("1"))
        )
        rows = (await self._session.execute(stmt)).all()
        return [(b, str(g), Decimal(v or 0)) for b, g, v in rows]

    async def distinct_total(
        self, metric: Metric, start: datetime, end: datetime, customer_id: UUID | None = None
    ) -> Decimal:
        """Distinct values across a whole window; summing per-bucket counts would double count."""
        stmt = select(_distinct_per_customer()).where(
            U.metric_id == metric.id, U.bucket_start >= start, U.bucket_start < end
        )
        if customer_id is not None:
            stmt = stmt.where(U.customer_id == customer_id)
        value = await self._session.scalar(stmt)
        return Decimal(value or 0)

    async def raw_total(
        self, metric: Metric, customer_id: UUID, start: datetime, end: datetime
    ) -> Decimal:
        """Recompute straight from the partitioned event log; used to audit the rollups."""
        params: dict[str, object] = {
            "customer_id": customer_id,
            "event_code": metric.event_code,
            "start": start,
            "end": end,
            "path": metric.path,
        }
        value_expr = "(properties #>> CAST(:path AS text[]))"
        measures = {
            Aggregation.COUNT: "count(*)",
            Aggregation.SUM: f"sum({value_expr}::numeric)",
            Aggregation.MAX: f"max({value_expr}::numeric)",
            Aggregation.UNIQUE_COUNT: f"count(DISTINCT {value_expr})",
        }
        where = (
            "customer_id = :customer_id AND event_code = :event_code"
            " AND timestamp >= :start AND timestamp < :end"
        )
        if metric.aggregation is Aggregation.LATEST:
            sql = (
                f"SELECT {value_expr}::numeric FROM usage_events WHERE {where}"
                " ORDER BY timestamp DESC, ingested_at DESC LIMIT 1"
            )
        else:
            sql = f"SELECT {measures[metric.aggregation]} FROM usage_events WHERE {where}"
        value = await self._session.scalar(text(sql), params)
        return Decimal(value or 0)


def _distinct_per_customer() -> ColumnElement[Any]:
    # The same user id under two customers is two users.
    return func.count(func.distinct(tuple_(U.customer_id, U.value)))


def _rollup_measure(aggregation: Aggregation) -> ColumnElement[Any]:
    match aggregation:
        case Aggregation.COUNT:
            return func.coalesce(func.sum(R.event_count), 0)
        case Aggregation.SUM:
            return func.coalesce(func.sum(R.sum_value), 0)
        case Aggregation.MAX:
            return func.max(R.max_value)
        case _:
            raise ValueError(f"{aggregation} is not a simple rollup measure")


def _rollup_window(
    metric_id: UUID, customer_id: UUID, start: datetime, end: datetime
) -> list[ColumnElement[bool]]:
    return [
        R.customer_id == customer_id,
        R.metric_id == metric_id,
        R.bucket_start >= start,
        R.bucket_start < end,
    ]


def _unique_window(
    metric_id: UUID, customer_id: UUID, start: datetime, end: datetime
) -> list[ColumnElement[bool]]:
    return [
        U.customer_id == customer_id,
        U.metric_id == metric_id,
        U.bucket_start >= start,
        U.bucket_start < end,
    ]
