from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from meterly.money import Currency, Money
from meterly.pricing import (
    GraduatedPrice,
    PackagePrice,
    PerUnitPrice,
    PriceModelAdapter,
    Tier,
    VolumePrice,
    price,
)

USD = Currency.USD

TIERS = [
    Tier(up_to=Decimal(1000), unit_price=Decimal("0.10")),
    Tier(up_to=Decimal(10000), unit_price=Decimal("0.05"), flat_fee=Decimal("5")),
    Tier(up_to=None, unit_price=Decimal("0.01")),
]


def test_discriminated_union_parses_by_model_field() -> None:
    parsed = PriceModelAdapter.validate_python(
        {"model": "package", "package_size": "1000", "package_price": "2.50"}
    )
    assert isinstance(parsed, PackagePrice)


def test_tiers_must_end_open_and_ascend() -> None:
    with pytest.raises(ValidationError, match="open-ended"):
        GraduatedPrice(tiers=[Tier(up_to=Decimal(10), unit_price=Decimal(1))])
    with pytest.raises(ValidationError, match="strictly increasing"):
        VolumePrice(
            tiers=[
                Tier(up_to=Decimal(10), unit_price=Decimal(1)),
                Tier(up_to=Decimal(5), unit_price=Decimal(1)),
                Tier(up_to=None, unit_price=Decimal(1)),
            ]
        )


def test_graduated_prices_each_slice() -> None:
    result = price(GraduatedPrice(tiers=TIERS), Decimal(12000), USD)
    assert [c.units for c in result.components] == [Decimal(1000), Decimal(9000), Decimal(2000)]
    assert result.amount == Money.of("100", USD) + Money.of("455", USD) + Money.of("20", USD)


def test_volume_prices_whole_quantity_at_landing_tier() -> None:
    result = price(VolumePrice(tiers=TIERS), Decimal(12000), USD)
    assert result.amount == Money.of("120.00", USD)
    assert len(result.components) == 1


def test_package_rounds_partial_packages_up() -> None:
    result = price(
        PackagePrice(package_size=Decimal(1000), package_price=Decimal("2.50")), Decimal(2001), USD
    )
    assert result.amount == Money.of("7.50", USD)


def test_free_units_are_deducted_first() -> None:
    model = PerUnitPrice(unit_price=Decimal("0.002"), free_units=Decimal(1000))
    assert price(model, Decimal(800), USD).amount.is_zero()
    assert price(model, Decimal(1500), USD).amount == Money.of("1.00", USD)


def test_sub_cent_unit_prices_round_half_even_once() -> None:
    model = PerUnitPrice(unit_price=Decimal("0.0005"))
    assert price(model, Decimal(25), USD).amount == Money.of("0.01", USD)
    assert price(model, Decimal(30), USD).amount == Money.of("0.02", USD)


quantities = st.decimals(min_value=0, max_value=10**9, places=3, allow_nan=False)
unit_prices = st.decimals(min_value=0, max_value=100, places=6, allow_nan=False)


@st.composite
def tier_lists(draw: st.DrawFn) -> list[Tier]:
    bounds = sorted(
        draw(st.sets(st.integers(min_value=1, max_value=10**7), min_size=0, max_size=6))
    )
    uppers: list[Decimal | None] = [Decimal(b) for b in bounds]
    uppers.append(None)
    return [Tier(up_to=u, unit_price=draw(unit_prices), flat_fee=draw(unit_prices)) for u in uppers]


@given(tier_lists(), quantities, st.sampled_from(list(Currency)))
def test_graduated_slices_cover_quantity_and_reconcile(
    tiers: list[Tier], quantity: Decimal, currency: Currency
) -> None:
    result = price(GraduatedPrice(tiers=tiers), quantity, currency)
    assert sum((c.units for c in result.components), Decimal(0)) == quantity
    assert sum((c.exact for c in result.components), Decimal(0)) == result.exact
    assert result.amount == Money.of(result.exact, currency)
    assert Money.total((c.amount for c in result.components), currency) == result.amount


@given(tier_lists(), quantities, quantities)
def test_graduated_is_monotonic(tiers: list[Tier], a: Decimal, b: Decimal) -> None:
    model = GraduatedPrice(tiers=tiers)
    low, high = sorted((a, b))
    assert price(model, low, USD).exact <= price(model, high, USD).exact


@given(tier_lists(), quantities)
def test_volume_and_graduated_agree_with_single_tier(tiers: list[Tier], quantity: Decimal) -> None:
    single = [Tier(up_to=None, unit_price=tiers[0].unit_price)]
    assert (
        price(VolumePrice(tiers=single), quantity, USD).amount
        == price(GraduatedPrice(tiers=single), quantity, USD).amount
        == price(PerUnitPrice(unit_price=tiers[0].unit_price), quantity, USD).amount
    )


@given(unit_prices, quantities, quantities)
def test_free_units_shift_the_curve(unit: Decimal, quantity: Decimal, free: Decimal) -> None:
    with_free = price(PerUnitPrice(unit_price=unit, free_units=free), quantity, USD)
    shifted = price(PerUnitPrice(unit_price=unit), max(quantity - free, Decimal(0)), USD)
    assert with_free.amount == shifted.amount
