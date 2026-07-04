from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from meterly.api.deps import CustomersDep, MeteringDep
from meterly.metering.definitions import Metric, MetricDefinition
from meterly.metering.repository import Granularity
from meterly.metering.service import Reconciliation, UsageSeries

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


@router.get("")
async def list_metrics(service: MeteringDep) -> list[Metric]:
    return await service.metrics()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_metric(definition: MetricDefinition, service: MeteringDep) -> Metric:
    return await service.create(definition)


@router.get("/{code}/usage")
async def metric_usage(
    code: str,
    service: MeteringDep,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    granularity: Granularity = "day",
    by_group: bool = False,
) -> UsageSeries:
    return await service.series(code, days=days, granularity=granularity, by_group=by_group)


@router.get("/{code}/reconcile")
async def reconcile(
    code: str,
    customer_id: str,
    start: datetime,
    end: datetime,
    service: MeteringDep,
    customers: CustomersDep,
) -> Reconciliation:
    """Compare the rollup answer against a full scan of the raw event log."""
    customer = await customers.require(customer_id)
    return await service.reconcile(code, customer.id, start, end)
