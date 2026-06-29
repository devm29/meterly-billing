from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.config import Settings
from meterly.errors import InvalidRequestError
from meterly.ingestion.repository import IngestionRepository, NewEvent
from meterly.ingestion.rollups import fold
from meterly.ingestion.schemas import (
    EventBatchOut,
    EventPage,
    EventResult,
    ItemError,
    ItemStatus,
    StoredEvent,
    UsageEventIn,
)
from meterly.log import get_logger
from meterly.metering.definitions import (
    ExtractionError,
    Metric,
    MissingPropertyError,
    Reading,
    read,
)
from meterly.metering.locks import share_metric_definitions
from meterly.metering.repository import MetricRepository

log = get_logger(__name__)
_MAX_ATTEMPTS = 3
_RETRYABLE = {"40P01", "40001"}
_event_adapter = TypeAdapter(UsageEventIn)


class CacheInvalidator(Protocol):
    async def invalidate(self, customer_ids: Sequence[UUID]) -> None: ...


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        invalidator: CacheInvalidator,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._settings = settings
        self._invalidator = invalidator
        self._clock = clock
        self._events = IngestionRepository(session)
        self._metrics = MetricRepository(session)

    async def ingest(self, raw_events: Sequence[JsonValue]) -> EventBatchOut:
        if len(raw_events) > self._settings.max_batch_size:
            raise InvalidRequestError(
                f"batch has {len(raw_events)} events; the limit is {self._settings.max_batch_size}"
            )
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self._ingest_once(raw_events)
            except DBAPIError as exc:
                await self._session.rollback()
                sqlstate = getattr(exc.orig, "sqlstate", None)
                if sqlstate not in _RETRYABLE or attempt == _MAX_ATTEMPTS:
                    raise
                # Replaying is safe: the idempotency ledger rolled back with the transaction.
                log.warning("events.retry", attempt=attempt, sqlstate=sqlstate)
                await asyncio.sleep(0.02 * attempt)
        raise AssertionError("unreachable")

    async def _ingest_once(self, raw_events: Sequence[JsonValue]) -> EventBatchOut:
        now = self._clock()
        results: list[EventResult | None] = [None] * len(raw_events)
        parsed: list[tuple[int, UsageEventIn]] = []
        for index, raw in enumerate(raw_events):
            if not isinstance(raw, dict):
                results[index] = _rejected(
                    index, None, "invalid_event", "event: each item must be a JSON object"
                )
                continue
            try:
                parsed.append((index, _event_adapter.validate_python(raw)))
            except ValidationError as exc:
                txn = raw.get("transaction_id")
                results[index] = _rejected(
                    index, txn if isinstance(txn, str) else None, "invalid_event", _first_error(exc)
                )

        await share_metric_definitions(self._session)
        customers = await self._events.customers(e.customer_id for _, e in parsed)
        metrics_by_event = await self._metrics.by_event_codes([e.code for _, e in parsed])
        max_future = now + timedelta(seconds=self._settings.max_future_skew_seconds)
        late_before = now - timedelta(minutes=self._settings.late_event_threshold_minutes)

        candidates: list[tuple[int, NewEvent, list[Reading], list[ItemError]]] = []
        seen_in_batch: set[tuple[UUID, str]] = set()
        for index, event in parsed:
            ts = event.timestamp.astimezone(UTC)
            customer = customers.get(event.customer_id)
            if customer is None:
                results[index] = _rejected(
                    index,
                    event.transaction_id,
                    "unknown_customer",
                    f"no customer with external id {event.customer_id!r}",
                )
                continue
            if ts > max_future:
                results[index] = _rejected(
                    index,
                    event.transaction_id,
                    "timestamp_in_future",
                    "event timestamp is ahead of the server clock",
                )
                continue
            if customer.closed_through is not None and ts.date() < customer.closed_through:
                results[index] = _rejected(
                    index,
                    event.transaction_id,
                    "period_closed",
                    f"the billing period containing {ts.date()} is already invoiced",
                )
                continue
            try:
                readings, warnings = _readings(metrics_by_event.get(event.code, []), event)
            except ExtractionError as exc:
                results[index] = _rejected(index, event.transaction_id, exc.code, str(exc))
                continue

            key = (customer.id, event.transaction_id)
            if key in seen_in_batch:
                results[index] = EventResult(
                    index=index, transaction_id=event.transaction_id, status=ItemStatus.DUPLICATE
                )
                continue
            seen_in_batch.add(key)
            new = NewEvent(customer.id, event.transaction_id, event.code, ts, event.properties)
            candidates.append((index, new, readings, warnings))

        claimed = await self._events.claim_keys([c[1] for c in candidates]) if candidates else set()
        accepted: list[tuple[int, NewEvent, list[Reading]]] = []
        for index, new, readings, warnings in candidates:
            if (new.customer_id, new.transaction_id) in claimed:
                accepted.append((index, new, readings))
                results[index] = EventResult(
                    index=index,
                    transaction_id=new.transaction_id,
                    status=ItemStatus.ACCEPTED,
                    late=new.timestamp < late_before,
                    warnings=warnings,
                )
            else:
                results[index] = EventResult(
                    index=index, transaction_id=new.transaction_id, status=ItemStatus.DUPLICATE
                )

        if accepted:
            await self._events.insert_events([a[1] for a in accepted])
            deltas = fold(
                (new.customer_id, new.timestamp, reading)
                for _, new, readings in accepted
                for reading in readings
            )
            await self._events.upsert_rollups(deltas)
        await self._session.commit()

        affected = sorted({new.customer_id for _, new, _ in accepted}, key=str)
        if affected:
            await self._invalidator.invalidate(affected)

        final = [r for r in results if r is not None]
        out = EventBatchOut(
            accepted=sum(r.status is ItemStatus.ACCEPTED for r in final),
            duplicates=sum(r.status is ItemStatus.DUPLICATE for r in final),
            rejected=sum(r.status is ItemStatus.REJECTED for r in final),
            results=final,
        )
        log.info(
            "events.ingested",
            accepted=out.accepted,
            duplicates=out.duplicates,
            rejected=out.rejected,
        )
        return out

    async def recent(
        self, customer_id: UUID | None, *, days: int, limit: int, cursor: str | None
    ) -> EventPage:
        since = self._clock() - timedelta(days=days)
        before = decode_cursor(cursor) if cursor else None
        rows = await self._events.recent_events(customer_id, since, limit, before)
        external = await self._events.external_ids(e.customer_id for e in rows)
        items = [
            StoredEvent(
                id=str(e.id),
                customer_id=external.get(e.customer_id, str(e.customer_id)),
                transaction_id=e.transaction_id,
                code=e.event_code,
                timestamp=e.timestamp,
                properties=e.properties,
                ingested_at=e.ingested_at,
            )
            for e in rows
        ]
        last = rows[-1] if len(rows) == limit else None
        return EventPage(
            items=items, next_cursor=encode_cursor(last.timestamp, last.id) if last else None
        )


def encode_cursor(timestamp: datetime, event_id: UUID) -> str:
    raw = f"{timestamp.isoformat()}|{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts, _, event_id = base64.urlsafe_b64decode(padded).decode().partition("|")
        moment = datetime.fromisoformat(ts)
        if moment.tzinfo is None:
            raise ValueError("cursor timestamp has no offset")
        return moment, UUID(event_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidRequestError("invalid cursor") from exc


def _readings(
    metrics: Sequence[Metric], event: UsageEventIn
) -> tuple[list[Reading], list[ItemError]]:
    """A metric whose property is absent is skipped with a warning; it must never cost the
    other metrics on the same event (an analytics metric must not drop billable usage).
    A property that is present but malformed is still a hard rejection."""
    readings: list[Reading] = []
    warnings: list[ItemError] = []
    for metric in metrics:
        try:
            readings.append(read(metric, event.properties))
        except MissingPropertyError as exc:
            warnings.append(ItemError(code=exc.code, message=str(exc)))
    return readings, warnings


def _rejected(index: int, txn: str | None, code: str, message: str) -> EventResult:
    return EventResult(
        index=index,
        transaction_id=txn,
        status=ItemStatus.REJECTED,
        error=ItemError(code=code, message=message),
    )


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    location = ".".join(str(p) for p in err["loc"]) or "event"
    return f"{location}: {err['msg']}"
