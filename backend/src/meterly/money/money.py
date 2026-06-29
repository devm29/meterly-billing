from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from enum import StrEnum


class Currency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"

    @property
    def exponent(self) -> int:
        return 0 if self is Currency.JPY else 2

    @property
    def quantum(self) -> Decimal:
        return Decimal(1).scaleb(-self.exponent)


def round_half_even(value: Decimal, currency: Currency) -> Decimal:
    """Banker's rounding to the currency's minor unit; the only rounding rule for settled money."""
    return value.quantize(currency.quantum, rounding=ROUND_HALF_EVEN)


class CurrencyMismatchError(ValueError):
    pass


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """A settled amount, always expressed exactly in the currency's minor units."""

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValueError(f"Money amount must be a finite Decimal, got {self.amount!r}")
        if self.amount != round_half_even(self.amount, self.currency):
            raise ValueError(
                f"{self.amount} has more precision than {self.currency} allows; use Money.of()"
            )
        object.__setattr__(self, "amount", self.amount.quantize(self.currency.quantum))

    @classmethod
    def of(cls, value: Decimal | int | str, currency: Currency) -> Money:
        return cls(round_half_even(Decimal(value), currency), currency)

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        return cls(Decimal(0), currency)

    @classmethod
    def from_minor(cls, minor: int, currency: Currency) -> Money:
        return cls(Decimal(minor).scaleb(-currency.exponent), currency)

    @classmethod
    def total(cls, items: Iterable[Money], currency: Currency) -> Money:
        result = cls.zero(currency)
        for item in items:
            result = result + item
        return result

    @property
    def minor_units(self) -> int:
        return int(self.amount.scaleb(self.currency.exponent))

    def _check(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise CurrencyMismatchError(f"{self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._check(other)
        return self.amount >= other.amount

    def is_zero(self) -> bool:
        return self.amount == 0

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


def allocate(total: Money, weights: Sequence[Decimal]) -> list[Money]:
    """Split ``total`` proportionally to ``weights`` using the largest-remainder method.

    The parts always sum to exactly ``total``: rounding residue is handed out one minor
    unit at a time to the parts with the largest truncated remainder, ties broken by
    position so results are deterministic.
    """
    if not weights:
        return []
    if any(w < 0 for w in weights):
        raise ValueError("allocation weights must be non-negative")

    weight_sum = sum(weights, Decimal(0))
    effective = list(weights) if weight_sum > 0 else [Decimal(1)] * len(weights)
    weight_sum = sum(effective, Decimal(0))

    sign = -1 if total.amount < 0 else 1
    total_minor = abs(total.minor_units)

    shares = [Decimal(total_minor) * w / weight_sum for w in effective]
    floors = [int(s.to_integral_value(rounding=ROUND_DOWN)) for s in shares]
    residue = total_minor - sum(floors)

    order = sorted(range(len(shares)), key=lambda i: (-(shares[i] - floors[i]), i))
    for i in order[:residue]:
        floors[i] += 1

    return [Money.from_minor(sign * minor, total.currency) for minor in floors]
