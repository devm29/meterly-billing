from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from meterly.ingestion.repository import IngestionRepository
from meterly.ingestion.rollups import RollupDelta, RollupKey, accumulate, ordered
from meterly.metering.definitions import ExtractionError, Metric, read


@dataclass(frozen=True, slots=True)
class BackfillResult:
    events: int
    skipped: int


async def backfill_metric(session: AsyncSession, metric: Metric) -> BackfillResult:
    """Fold every stored event of the metric's event code into its rollups.

    Must run in the transaction that created the metric, under the exclusive metric lock,
    so no concurrent batch can fold the same events a second time.
    """
    repo = IngestionRepository(session)
    deltas: dict[RollupKey, RollupDelta] = {}
    events = skipped = 0
    async for event in repo.stream_events(metric.event_code):
        try:
            reading = read(metric, event.properties)
        except ExtractionError:
            skipped += 1
            continue
        accumulate(deltas, event.customer_id, event.timestamp, reading)
        events += 1
    if deltas:
        await repo.upsert_rollups(ordered(deltas))
    return BackfillResult(events=events, skipped=skipped)
