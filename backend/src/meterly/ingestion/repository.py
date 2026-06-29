from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.statuses import InvoiceStatus
from meterly.db.models import (
    Customer,
    Invoice,
    UsageEvent,
    UsageEventKey,
    UsageRollupHourly,
    UsageUniqueValue,
)
from meterly.ingestion.rollups import RollupDelta, RollupKey

R = UsageRollupHourly
_CHUNK = 2000


@dataclass(frozen=True, slots=True)
class CustomerRef:
    id: UUID
    external_id: str
    closed_through: date | None


@dataclass(frozen=True, slots=True)
class NewEvent:
    customer_id: UUID
    transaction_id: str
    event_code: str
    timestamp: datetime
    properties: dict[str, Any]


def _chunks[T](items: Sequence[T], size: int = _CHUNK) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class IngestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def customers(self, external_ids: Iterable[str]) -> dict[str, CustomerRef]:
        """Resolve customers and how far they are invoiced, holding a share lock on each.

        Period close takes a conflicting lock on the customer before it snapshots usage, so
        a batch either commits before the snapshot is taken or sees the invoice it produced.
        The invoiced-through read is a separate statement on purpose: under READ COMMITTED
        it gets a fresh snapshot after any wait on the row locks.
        """
        ids = set(external_ids)
        if not ids:
            return {}
        locked = (
            await self._session.execute(
                select(Customer.id, Customer.external_id)
                .where(Customer.external_id.in_(ids))
                .order_by(Customer.id)
                .with_for_update(read=True)
            )
        ).all()
        if not locked:
            return {}
        invoiced = await self._session.execute(
            select(Invoice.customer_id, func.max(Invoice.period_end))
            .where(
                Invoice.customer_id.in_([cid for cid, _ in locked]),
                Invoice.status != InvoiceStatus.VOID,
            )
            .group_by(Invoice.customer_id)
        )
        closed: dict[UUID, date] = dict(invoiced.all())
        return {ext: CustomerRef(cid, ext, closed.get(cid)) for cid, ext in locked}

    async def claim_keys(self, events: Sequence[NewEvent]) -> set[tuple[UUID, str]]:
        """Insert idempotency keys; only keys that were not seen before come back.

        Keys are inserted in a canonical order so concurrent batches that overlap always
        wait on each other in the same sequence instead of deadlocking.
        """
        ordered = sorted(events, key=lambda e: (str(e.customer_id), e.transaction_id))
        claimed: set[tuple[UUID, str]] = set()
        for chunk in _chunks(ordered):
            stmt = (
                pg_insert(UsageEventKey)
                .values(
                    [
                        {
                            "customer_id": e.customer_id,
                            "transaction_id": e.transaction_id,
                            "event_timestamp": e.timestamp,
                        }
                        for e in chunk
                    ]
                )
                .on_conflict_do_nothing(index_elements=["customer_id", "transaction_id"])
                .returning(UsageEventKey.customer_id, UsageEventKey.transaction_id)
            )
            claimed.update((cid, txn) for cid, txn in await self._session.execute(stmt))
        return claimed

    async def insert_events(self, events: Sequence[NewEvent]) -> None:
        for chunk in _chunks(events):
            await self._session.execute(
                pg_insert(UsageEvent).values(
                    [
                        {
                            "customer_id": e.customer_id,
                            "transaction_id": e.transaction_id,
                            "event_code": e.event_code,
                            "timestamp": e.timestamp,
                            "properties": e.properties,
                        }
                        for e in chunk
                    ]
                )
            )

    async def upsert_rollups(self, deltas: dict[RollupKey, RollupDelta]) -> None:
        rows = [
            {
                "customer_id": customer_id,
                "metric_id": metric_id,
                "bucket_start": bucket,
                "group_key": group_key,
                "event_count": d.event_count,
                "sum_value": d.sum_value,
                "max_value": d.max_value,
                "latest_value": d.latest_value,
                "latest_at": d.latest_at,
            }
            for (customer_id, metric_id, bucket, group_key), d in deltas.items()
        ]
        for chunk in _chunks(rows):
            stmt = pg_insert(R).values(list(chunk))
            ex = stmt.excluded
            newer = or_(R.latest_at.is_(None), ex.latest_at >= R.latest_at)
            await self._session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["customer_id", "metric_id", "bucket_start", "group_key"],
                    set_={
                        "event_count": R.event_count + ex.event_count,
                        "sum_value": R.sum_value + ex.sum_value,
                        "max_value": func.greatest(R.max_value, ex.max_value),
                        "latest_value": case(
                            (ex.latest_at.is_(None), R.latest_value),
                            (newer, ex.latest_value),
                            else_=R.latest_value,
                        ),
                        "latest_at": func.greatest(R.latest_at, ex.latest_at),
                        "updated_at": func.now(),
                    },
                )
            )

        distinct_rows = [
            {
                "customer_id": customer_id,
                "metric_id": metric_id,
                "bucket_start": bucket,
                "group_key": group_key,
                "value": value,
            }
            for (customer_id, metric_id, bucket, group_key), d in deltas.items()
            for value in sorted(d.distinct)
        ]
        for batch in _chunks(distinct_rows):
            await self._session.execute(
                pg_insert(UsageUniqueValue).values(list(batch)).on_conflict_do_nothing()
            )

    async def recent_events(
        self,
        customer_id: UUID | None,
        since: datetime,
        limit: int,
        before: tuple[datetime, UUID] | None,
    ) -> list[UsageEvent]:
        stmt = (
            select(UsageEvent)
            .where(UsageEvent.timestamp >= since)
            .order_by(UsageEvent.timestamp.desc(), UsageEvent.id.desc())
        )
        if customer_id is not None:
            stmt = stmt.where(UsageEvent.customer_id == customer_id)
        if before is not None:
            stmt = stmt.where(tuple_(UsageEvent.timestamp, UsageEvent.id) < tuple_(*before))
        return list(await self._session.scalars(stmt.limit(limit)))

    async def external_ids(self, customer_ids: Iterable[UUID]) -> dict[UUID, str]:
        ids = set(customer_ids)
        if not ids:
            return {}
        rows = await self._session.execute(
            select(Customer.id, Customer.external_id).where(Customer.id.in_(ids))
        )
        return dict(rows.all())

    async def stream_events(self, event_code: str, chunk: int = 5000) -> AsyncIterator[UsageEvent]:
        result = await self._session.stream_scalars(
            select(UsageEvent)
            .where(UsageEvent.event_code == event_code)
            .execution_options(yield_per=chunk)
        )
        async for event in result:
            yield event
