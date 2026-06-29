from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.analytics.service import AnalyticsService
from meterly.api.container import Container
from meterly.billing.customers import CustomerService
from meterly.billing.invoicing import InvoiceService
from meterly.billing.plans import PlanService
from meterly.billing.simulator import PricingSimulator
from meterly.billing.subscriptions import SubscriptionService
from meterly.entitlements.service import EntitlementService
from meterly.ingestion.service import IngestionService
from meterly.metering.service import MeteringService


def container(request: Request) -> Container:
    state: Container = request.app.state.container
    return state


ContainerDep = Annotated[Container, Depends(container)]


async def session(c: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with c.sessions() as s:
        yield s


SessionDep = Annotated[AsyncSession, Depends(session)]


class Page:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PageDep = Annotated[Page, Depends()]


def ingestion(s: SessionDep, c: ContainerDep) -> IngestionService:
    return IngestionService(s, c.settings, c.cache)


def metering(s: SessionDep) -> MeteringService:
    return MeteringService(s)


def customers(s: SessionDep) -> CustomerService:
    return CustomerService(s)


def plans(s: SessionDep) -> PlanService:
    return PlanService(s)


def subscriptions(s: SessionDep, c: ContainerDep) -> SubscriptionService:
    return SubscriptionService(s, c.cache)


def invoices(s: SessionDep, c: ContainerDep) -> InvoiceService:
    return InvoiceService(s, c.settings, c.renderer)


def entitlements(s: SessionDep, c: ContainerDep) -> EntitlementService:
    return EntitlementService(s, c.cache, c.settings)


def analytics(s: SessionDep) -> AnalyticsService:
    return AnalyticsService(s)


def simulator(s: SessionDep) -> PricingSimulator:
    return PricingSimulator(s)


IngestionDep = Annotated[IngestionService, Depends(ingestion)]
MeteringDep = Annotated[MeteringService, Depends(metering)]
CustomersDep = Annotated[CustomerService, Depends(customers)]
PlansDep = Annotated[PlanService, Depends(plans)]
SubscriptionsDep = Annotated[SubscriptionService, Depends(subscriptions)]
InvoicesDep = Annotated[InvoiceService, Depends(invoices)]
EntitlementsDep = Annotated[EntitlementService, Depends(entitlements)]
AnalyticsDep = Annotated[AnalyticsService, Depends(analytics)]
SimulatorDep = Annotated[PricingSimulator, Depends(simulator)]
