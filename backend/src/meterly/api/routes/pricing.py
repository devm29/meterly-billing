from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from meterly.api.deps import SimulatorDep
from meterly.billing.simulator import SimulationOut, SimulationRequest
from meterly.money import Currency
from meterly.pricing import PricedQuantity, PriceModel, price

router = APIRouter(prefix="/v1", tags=["pricing"])


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: PriceModel
    quantity: Annotated[Decimal, Field(ge=0, max_digits=30, decimal_places=10)]
    currency: Currency = Currency.USD


@router.post("/pricing/quote")
async def quote(request: QuoteRequest) -> PricedQuantity:
    """Price a quantity with any price model; pure, no persistence."""
    return price(request.price, request.quantity, request.currency)


@router.post("/simulations")
async def simulate(request: SimulationRequest, service: SimulatorDep) -> SimulationOut:
    return await service.simulate(request)
