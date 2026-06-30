from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

Amount = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=10)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=30, decimal_places=10)]
PositiveQuantity = Annotated[Decimal, Field(gt=0, max_digits=30, decimal_places=10)]


class _PriceBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FlatPrice(_PriceBase):
    """A fixed recurring fee for the billing period, independent of usage."""

    model: Literal["flat"] = "flat"
    amount: Amount


class _UsagePrice(_PriceBase):
    free_units: Quantity = Decimal(0)


class PerUnitPrice(_UsagePrice):
    model: Literal["per_unit"] = "per_unit"
    unit_price: Amount


class PackagePrice(_UsagePrice):
    """Units are sold in packages; a partially used package is billed in full."""

    model: Literal["package"] = "package"
    package_size: PositiveQuantity
    package_price: Amount


class Tier(_PriceBase):
    up_to: PositiveQuantity | None
    unit_price: Amount
    flat_fee: Amount = Decimal(0)


class _TieredPrice(_UsagePrice):
    tiers: Annotated[list[Tier], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def _tiers_are_ordered(self) -> _TieredPrice:
        *bounded, last = self.tiers
        if last.up_to is not None:
            raise ValueError("the last tier must be open-ended (up_to = null)")
        previous = Decimal(0)
        for tier in bounded:
            if tier.up_to is None:
                raise ValueError("only the last tier may be open-ended")
            if tier.up_to <= previous:
                raise ValueError("tier bounds must be strictly increasing")
            previous = tier.up_to
        return self


class VolumePrice(_TieredPrice):
    """The whole quantity is priced at the rate of the tier it lands in."""

    model: Literal["volume"] = "volume"


class GraduatedPrice(_TieredPrice):
    """Each slice of the quantity is priced at the rate of the tier it falls into."""

    model: Literal["graduated"] = "graduated"


UsagePriceModel = Annotated[
    PerUnitPrice | PackagePrice | VolumePrice | GraduatedPrice,
    Field(discriminator="model"),
]
PriceModel = Annotated[
    FlatPrice | PerUnitPrice | PackagePrice | VolumePrice | GraduatedPrice,
    Field(discriminator="model"),
]
PriceModelAdapter: TypeAdapter[PriceModel] = TypeAdapter(PriceModel)
