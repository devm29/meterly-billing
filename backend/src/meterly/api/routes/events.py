from typing import Annotated

from fastapi import APIRouter, Query, status

from meterly.api.auth import RequireAdmin, RequireIngest
from meterly.api.deps import CustomersDep, IngestionDep
from meterly.ingestion.schemas import EventBatchIn, EventBatchOut, EventPage

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED, dependencies=[RequireIngest])
async def ingest_batch(batch: EventBatchIn, service: IngestionDep) -> EventBatchOut:
    """Idempotent on (customer, transaction_id); every item gets its own status."""
    return await service.ingest(batch.events)


@router.get("", dependencies=[RequireAdmin])
async def recent_events(
    service: IngestionDep,
    customers: CustomersDep,
    customer_id: str | None = None,
    days: Annotated[int, Query(ge=1, le=366, description="Look-back window")] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=200, description="next_cursor")] = None,
) -> EventPage:
    customer = await customers.require(customer_id) if customer_id else None
    return await service.recent(
        customer.id if customer else None, days=days, limit=limit, cursor=cursor
    )
