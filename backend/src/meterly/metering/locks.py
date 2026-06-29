"""Advisory lock that orders metric creation against ingestion.

Ingestion holds it shared for the whole batch transaction; creating a metric takes it
exclusively while it inserts the definition and backfills rollups from the raw log. Every
event is therefore folded into a new metric's rollups exactly once: either by the backfill
(it committed before the metric existed) or by ingestion (it saw the metric).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_METRIC_DEFINITIONS_KEY = 0x6D74_7231


async def share_metric_definitions(session: AsyncSession) -> None:
    await session.execute(select(func.pg_advisory_xact_lock_shared(_METRIC_DEFINITIONS_KEY)))


async def lock_metric_definitions(session: AsyncSession) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(_METRIC_DEFINITIONS_KEY)))
