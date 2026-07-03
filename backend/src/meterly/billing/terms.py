from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from meterly.billing.periods import Interval
from meterly.money import Currency
from meterly.pricing.models import Amount, FlatPrice, PriceModel, Quantity
from meterly.types import Slug


class Charge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: Slug
    name: Annotated[str, Field(min_length=1, max_length=120)]
    metric_code: Slug | None = None
    price: PriceModel
    minimum_amount: Amount | None = None

    @model_validator(mode="after")
    def _metric_matches_model(self) -> Charge:
        is_flat = isinstance(self.price, FlatPrice)
        if is_flat and self.metric_code is not None:
            raise ValueError(f"charge {self.key!r}: flat prices are not tied to a metric")
        if not is_flat and self.metric_code is None:
            raise ValueError(f"charge {self.key!r}: usage prices need a metric_code")
        return self


class FeatureEntitlement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: Slug
    name: Annotated[str, Field(min_length=1, max_length=120)]
    metric_code: Slug | None = None
    limit: Quantity | None = None


class PlanTerms(BaseModel):
    """Everything that is frozen into a plan version and drives what a customer pays."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: Currency
    interval: Interval = Interval.MONTH
    trial_days: Annotated[int, Field(ge=0, le=365)] = 0
    minimum_commitment: Amount | None = None
    charges: Annotated[list[Charge], Field(min_length=1, max_length=50)]
    entitlements: Annotated[list[FeatureEntitlement], Field(max_length=50)] = []

    @model_validator(mode="after")
    def _unique_keys(self) -> PlanTerms:
        keys = [c.key for c in self.charges]
        if len(keys) != len(set(keys)):
            raise ValueError("charge keys must be unique within a plan version")
        features = [e.feature for e in self.entitlements]
        if len(features) != len(set(features)):
            raise ValueError("entitlement features must be unique within a plan version")
        return self

    @property
    def metric_codes(self) -> set[str]:
        codes = {c.metric_code for c in self.charges if c.metric_code}
        codes |= {e.metric_code for e in self.entitlements if e.metric_code}
        return codes

    def fixed_amount(self) -> Decimal:
        return sum(
            (c.price.amount for c in self.charges if isinstance(c.price, FlatPrice)), Decimal(0)
        )
