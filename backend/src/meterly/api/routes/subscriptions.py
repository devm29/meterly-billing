from uuid import UUID

from fastapi import APIRouter, status

from meterly.api.deps import SubscriptionsDep
from meterly.billing.schemas import (
    Cancellation,
    PlanChange,
    PlanChangeOut,
    SubscriptionCreate,
    SubscriptionOut,
    UpcomingInvoiceOut,
)

router = APIRouter(prefix="/v1/subscriptions", tags=["subscriptions"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    payload: SubscriptionCreate, service: SubscriptionsDep
) -> SubscriptionOut:
    return await service.create(payload)


@router.get("/{subscription_id}")
async def get_subscription(subscription_id: UUID, service: SubscriptionsDep) -> SubscriptionOut:
    return await service.get(subscription_id)


@router.get("/{subscription_id}/upcoming-invoice")
async def upcoming_invoice(subscription_id: UUID, service: SubscriptionsDep) -> UpcomingInvoiceOut:
    return await service.upcoming_invoice(subscription_id)


@router.post("/{subscription_id}/change-plan")
async def change_plan(
    subscription_id: UUID, change: PlanChange, service: SubscriptionsDep
) -> PlanChangeOut:
    """Mid-cycle upgrade or downgrade; set dry_run to preview the day-based proration."""
    return await service.change_plan(subscription_id, change)


@router.post("/{subscription_id}/cancel")
async def cancel(
    subscription_id: UUID, cancellation: Cancellation, service: SubscriptionsDep
) -> SubscriptionOut:
    return await service.cancel(subscription_id, cancellation)
