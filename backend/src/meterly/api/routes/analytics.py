from typing import Annotated

from fastapi import APIRouter, Query

from meterly.analytics.service import Overview, RevenueMonth
from meterly.api.deps import AnalyticsDep
from meterly.money import Currency

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


@router.get("/overview")
async def overview(service: AnalyticsDep, currency: Currency = Currency.USD) -> Overview:
    return await service.overview(currency)


@router.get("/revenue")
async def revenue(
    service: AnalyticsDep,
    currency: Currency = Currency.USD,
    months: Annotated[int, Query(ge=1, le=36)] = 12,
) -> list[RevenueMonth]:
    return await service.revenue(currency, months)
