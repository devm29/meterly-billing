"""Pure pricing: (price model, quantity, currency) -> money. No I/O, no clocks."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal, localcontext
from typing import assert_never

from pydantic import BaseModel, ConfigDict

from meterly.money import Currency, Money, allocate
from meterly.pricing.models import (
    FlatPrice,
    GraduatedPrice,
    PackagePrice,
    PerUnitPrice,
    PriceModel,
    Tier,
    VolumePrice,
)


class PriceComponent(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    units: Decimal
    unit_price: Decimal | None
    flat_fee: Decimal
    exact: Decimal
    amount: Money


class PricedQuantity(BaseModel):
    model_config = ConfigDict(frozen=True)

    quantity: Decimal
    billable_quantity: Decimal
    exact: Decimal
    amount: Money
    components: tuple[PriceComponent, ...]


type _Draft = tuple[str, Decimal, Decimal | None, Decimal, Decimal]

# Quantities and prices carry up to 30 significant digits each, so their product needs ~60
# before the single half-even rounding to minor units; the default context (28) would round early.
WORKING_PRECISION = 60


def price(model: PriceModel, quantity: Decimal, currency: Currency) -> PricedQuantity:
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    with localcontext(prec=WORKING_PRECISION):
        return _price(model, quantity, currency)


def _price(model: PriceModel, quantity: Decimal, currency: Currency) -> PricedQuantity:
    billable = (
        quantity if isinstance(model, FlatPrice) else max(quantity - model.free_units, Decimal(0))
    )
    drafts = _components(model, billable)
    exact = sum((d[4] for d in drafts), Decimal(0))
    amount = Money.of(exact, currency)
    shares = allocate(amount, [d[4] for d in drafts]) if drafts else []

    components = tuple(
        PriceComponent(
            label=label, units=units, unit_price=unit_price, flat_fee=flat, exact=sub, amount=share
        )
        for (label, units, unit_price, flat, sub), share in zip(drafts, shares, strict=True)
    )
    return PricedQuantity(
        quantity=quantity,
        billable_quantity=billable,
        exact=exact,
        amount=amount,
        components=components,
    )


def _components(model: PriceModel, billable: Decimal) -> list[_Draft]:
    match model:
        case FlatPrice(amount=amount):
            return [("Flat fee", Decimal(1), amount, Decimal(0), amount)]
        case PerUnitPrice(unit_price=unit_price):
            if billable == 0:
                return []
            return [("Per unit", billable, unit_price, Decimal(0), billable * unit_price)]
        case PackagePrice(package_size=size, package_price=package_price):
            if billable == 0:
                return []
            packages = (billable / size).to_integral_value(rounding=ROUND_CEILING)
            label = f"{_fmt(packages)} × package of {_fmt(size)}"
            return [(label, packages, package_price, Decimal(0), packages * package_price)]
        case VolumePrice(tiers=tiers):
            return _volume(tiers, billable)
        case GraduatedPrice(tiers=tiers):
            return _graduated(tiers, billable)
        case _:
            assert_never(model)


def _volume(tiers: list[Tier], billable: Decimal) -> list[_Draft]:
    if billable == 0:
        return []
    lower = Decimal(0)
    for index, tier in enumerate(tiers, start=1):
        if tier.up_to is None or billable <= tier.up_to:
            label = f"Tier {index} ({_range(lower, tier.up_to)}), whole volume"
            sub = billable * tier.unit_price + tier.flat_fee
            return [(label, billable, tier.unit_price, tier.flat_fee, sub)]
        lower = tier.up_to
    raise AssertionError("validated tiers always end open-ended")


def _graduated(tiers: list[Tier], billable: Decimal) -> list[_Draft]:
    drafts: list[_Draft] = []
    lower = Decimal(0)
    for index, tier in enumerate(tiers, start=1):
        if billable <= lower:
            break
        upper = billable if tier.up_to is None else min(billable, tier.up_to)
        units = upper - lower
        label = f"Tier {index} ({_range(lower, tier.up_to)})"
        drafts.append(
            (label, units, tier.unit_price, tier.flat_fee, units * tier.unit_price + tier.flat_fee)
        )
        if tier.up_to is None:
            break
        lower = tier.up_to
    return drafts


def _range(lower: Decimal, upper: Decimal | None) -> str:
    return f"{_fmt(lower)}+" if upper is None else f"{_fmt(lower)}–{_fmt(upper)}"


def _fmt(value: Decimal) -> str:
    normalized = value.normalize()
    return f"{normalized:,f}" if normalized == normalized.to_integral_value() else f"{normalized:,}"
