from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from meterly.money import Currency, Money, allocate
from meterly.money.money import CurrencyMismatchError


def test_of_rounds_half_even() -> None:
    assert Money.of(Decimal("0.125"), Currency.USD).amount == Decimal("0.12")
    assert Money.of(Decimal("0.135"), Currency.USD).amount == Decimal("0.14")
    assert Money.of(Decimal("2.5"), Currency.JPY).amount == Decimal("2")


def test_constructor_rejects_sub_minor_precision() -> None:
    with pytest.raises(ValueError, match="more precision"):
        Money(Decimal("1.001"), Currency.USD)


def test_mixing_currencies_fails() -> None:
    with pytest.raises(CurrencyMismatchError):
        _ = Money.of(1, Currency.USD) + Money.of(1, Currency.EUR)


def test_allocate_spreads_residue_deterministically() -> None:
    parts = allocate(Money.of("100.00", Currency.USD), [Decimal(1)] * 3)
    assert [p.amount for p in parts] == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]


def test_allocate_zero_weights_split_evenly() -> None:
    parts = allocate(Money.of("0.05", Currency.USD), [Decimal(0), Decimal(0)])
    assert sum(p.amount for p in parts) == Decimal("0.05")


weights = st.lists(
    st.decimals(min_value=0, max_value=10**9, places=4, allow_nan=False), min_size=1, max_size=40
)
minor_totals = st.integers(min_value=-(10**12), max_value=10**12)


@given(minor_totals, weights, st.sampled_from(list(Currency)))
def test_allocation_never_loses_money(minor: int, ws: list[Decimal], currency: Currency) -> None:
    total = Money.from_minor(minor, currency)
    parts = allocate(total, ws)
    assert Money.total(parts, currency) == total
    weight_sum = sum(ws) or Decimal(len(ws))
    effective = ws if sum(ws) else [Decimal(1)] * len(ws)
    for part, w in zip(parts, effective, strict=True):
        ideal = Decimal(total.minor_units) * w / weight_sum
        assert abs(Decimal(part.minor_units) - ideal) < 1
