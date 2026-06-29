"""arq worker: closes billing periods, finalizes drafts and keeps event partitions ahead."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from meterly.billing.invoicing import run_close_cycle, store_documents
from meterly.billing.periods import add_months
from meterly.billing.render import InvoiceRenderer
from meterly.config import get_settings
from meterly.db.session import create_engine, create_session_factory
from meterly.log import configure_logging, get_logger

log = get_logger("meterly.worker")
Ctx = dict[str, Any]


async def startup(ctx: Ctx) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["sessions"] = create_session_factory(engine)
    ctx["renderer"] = InvoiceRenderer(settings)
    await ensure_partitions(ctx)


async def shutdown(ctx: Ctx) -> None:
    await ctx["engine"].dispose()


async def close_periods(ctx: Ctx) -> dict[str, int]:
    cycle = await run_close_cycle(ctx["sessions"], ctx["settings"], ctx["renderer"])
    summary = {
        "drafted": len(cycle.drafted),
        "finalized": len(cycle.finalized),
        "failed_subscriptions": len(cycle.failed_subscriptions),
        "failed_invoices": len(cycle.failed_invoices),
    }
    if any(summary.values()):
        log.info("billing.cycle", **summary)
    if cycle.finalized:
        await ctx["redis"].enqueue_job("render_documents")
    return summary


async def render_documents(ctx: Ctx) -> int:
    """Store PDFs for finalized invoices that have none yet (also catches earlier failures)."""
    stored = await store_documents(ctx["sessions"], ctx["settings"], ctx["renderer"])
    if stored:
        log.info("invoices.rendered", count=stored)
    return stored


async def ensure_partitions(ctx: Ctx) -> int:
    first_month = add_months(datetime.now(UTC).date().replace(day=1), -1)
    async with ctx["sessions"]() as session, session.begin():
        created = await session.scalar(
            text("SELECT meterly_ensure_event_partitions(:first, :months)"),
            {"first": first_month, "months": 6},
        )
    if created:
        log.info("partitions.created", count=created, from_month=str(first_month))
    return int(created or 0)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(get_settings().redis_url))


class WorkerSettings:
    functions: ClassVar[list[Any]] = [close_periods, render_documents, ensure_partitions]
    cron_jobs: ClassVar[list[Any]] = [
        cron(close_periods, second=0, run_at_startup=True, unique=True),
        cron(render_documents, minute=set(range(0, 60, 10)), second=30, unique=True),
        cron(ensure_partitions, hour={3}, minute={15}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _redis_settings()
    max_jobs = 4
