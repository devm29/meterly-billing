from typing import Annotated

from fastapi import APIRouter, Query, status

from meterly.api.auth import RequireAdmin, RequireIngest
from meterly.api.deps import (
    CustomersDep,
    EntitlementsDep,
    InvoicesDep,
    MeteringDep,
    PageDep,
)
from meterly.billing.customers import CustomerCreate, CustomerOut, CustomerPage
from meterly.billing.schemas import InvoiceSummary
from meterly.entitlements.service import EntitlementOut, EntitlementsOut
from meterly.metering.repository import Granularity
from meterly.metering.service import UsageSeries

router = APIRouter(prefix="/v1/customers", tags=["customers"])


@router.get("", dependencies=[RequireAdmin])
async def list_customers(
    service: CustomersDep, page: PageDep, q: Annotated[str | None, Query(max_length=100)] = None
) -> CustomerPage:
    return await service.search(q, page.limit, page.offset)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[RequireAdmin])
async def create_customer(payload: CustomerCreate, service: CustomersDep) -> CustomerOut:
    return await service.create(payload)


@router.get("/{customer_id}", dependencies=[RequireAdmin])
async def get_customer(customer_id: str, service: CustomersDep) -> CustomerOut:
    return await service.get(customer_id)


@router.get("/{customer_id}/usage", dependencies=[RequireAdmin])
async def customer_usage(
    customer_id: str,
    metric: str,
    customers: CustomersDep,
    metering: MeteringDep,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    granularity: Granularity = "day",
    by_group: bool = True,
) -> UsageSeries:
    customer = await customers.require(customer_id)
    return await metering.series(
        metric, days=days, granularity=granularity, customer_id=customer.id, by_group=by_group
    )


@router.get("/{customer_id}/invoices", dependencies=[RequireAdmin])
async def customer_invoices(
    customer_id: str, customers: CustomersDep, invoices: InvoicesDep, page: PageDep
) -> list[InvoiceSummary]:
    customer = await customers.require(customer_id)
    items, _ = await invoices.page(
        status=None, customer_id=customer.id, limit=page.limit, offset=page.offset
    )
    return items


@router.get("/{customer_id}/entitlements", dependencies=[RequireIngest])
async def list_entitlements(customer_id: str, service: EntitlementsDep) -> EntitlementsOut:
    return await service.all_for(customer_id)


@router.get("/{customer_id}/entitlements/{feature}", dependencies=[RequireIngest])
async def check_entitlement(
    customer_id: str, feature: str, service: EntitlementsDep
) -> EntitlementOut:
    """Hot path for product code: served from rollups behind a short-lived Redis cache."""
    return await service.check(customer_id, feature)
