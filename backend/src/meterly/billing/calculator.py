"""Turns a frozen usage snapshot into invoice lines. Pure: identical input, identical cents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from meterly.billing.periods import Period
from meterly.billing.terms import Charge, PlanTerms
from meterly.errors import InvalidRequestError
from meterly.metering.usage import MetricUsage
from meterly.money import Currency, Money, allocate
from meterly.pricing import FlatPrice, PriceComponent, PriceModel, UsagePriceModel, price
from meterly.pricing.engine import WORKING_PRECISION


class ChargeKindMismatchError(InvalidRequestError):
    code = "charge_kind_mismatch"

    def __init__(self, charge: Charge, model: PriceModel) -> None:
        expected = "a usage price" if charge.metric_code else "a flat price"
        super().__init__(
            f"charge {charge.key!r} needs {expected}; a {model.model!r} price cannot replace it"
        )


def check_override(charge: Charge, model: PriceModel) -> None:
    if isinstance(model, FlatPrice) != isinstance(charge.price, FlatPrice):
        raise ChargeKindMismatchError(charge, model)


class LineKind(StrEnum):
    FIXED = "fixed"
    USAGE = "usage"
    MINIMUM = "minimum"


class PhaseSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_version_id: UUID
    plan_name: str
    version: int
    terms: PlanTerms
    start: date
    end: date
    usage: dict[str, MetricUsage] = Field(default_factory=dict)

    @property
    def window(self) -> Period:
        return Period(self.start, self.end)


class UsageSnapshot(BaseModel):
    """The frozen inputs of an invoice: the full period and what was used in each phase."""

    model_config = ConfigDict(frozen=True)

    period_start: date
    period_end: date
    currency: Currency
    phases: list[PhaseSnapshot]

    @property
    def period(self) -> Period:
        return Period(self.period_start, self.period_end)


class AllocatedGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimensions: dict[str, str | None]
    quantity: Decimal
    amount: Money


class ComputedLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    kind: LineKind
    charge_key: str
    description: str
    metric_code: str | None
    plan_version_id: UUID
    phase_start: date
    phase_end: date
    proration: Decimal
    quantity: Decimal
    billable_quantity: Decimal
    exact: Decimal
    amount: Money
    components: tuple[PriceComponent, ...] = ()
    groups: tuple[AllocatedGroup, ...] = ()


def compute_lines(
    snapshot: UsageSnapshot, overrides: Mapping[str, PriceModel] | None = None
) -> list[ComputedLine]:
    """Price every phase of the snapshot.

    Rounding: each line is rounded once, half-even, to the currency minor unit; the invoice
    subtotal is the plain sum of rounded lines. Breakdowns (tiers, groups) are allocated
    with largest-remainder so they always reconcile to their line.
    """
    overrides = overrides or {}
    lines: list[ComputedLine] = []
    with localcontext(prec=WORKING_PRECISION):
        for phase in snapshot.phases:
            if phase.window.is_empty:
                continue
            lines.extend(_phase_lines(snapshot, phase, overrides))
    return lines


def subtotal(lines: list[ComputedLine], currency: Currency) -> Money:
    return Money.total((line.amount for line in lines), currency)


def _phase_lines(
    snapshot: UsageSnapshot, phase: PhaseSnapshot, overrides: Mapping[str, PriceModel]
) -> list[ComputedLine]:
    currency = snapshot.currency
    window = phase.window
    fraction = window.fraction_of(snapshot.period)
    prorated = window.days != snapshot.period.days
    suffix = f" · {window.days} of {snapshot.period.days} days" if prorated else ""

    lines: list[ComputedLine] = []
    for charge in phase.terms.charges:
        model = overrides.get(charge.key, charge.price)
        check_override(charge, model)
        if isinstance(model, FlatPrice):
            lines.append(_fixed_line(phase, charge, model, fraction, currency, suffix))
            continue
        if charge.metric_code is None:
            raise ChargeKindMismatchError(charge, model)
        usage_line = _usage_line(
            phase, charge, charge.metric_code, model, fraction, currency, suffix
        )
        lines.append(usage_line)
        if charge.minimum_amount is not None:
            floor = Money.of(charge.minimum_amount * fraction, currency)
            if usage_line.amount < floor:
                lines.append(
                    _minimum_line(
                        phase,
                        charge.key,
                        f"{charge.name} minimum spend{suffix}",
                        floor - usage_line.amount,
                        fraction,
                    )
                )

    commitment = phase.terms.minimum_commitment
    if commitment is not None:
        floor = Money.of(commitment * fraction, currency)
        usage_spend = Money.total(
            (line.amount for line in lines if line.kind is not LineKind.FIXED), currency
        )
        if usage_spend < floor:
            lines.append(
                _minimum_line(
                    phase,
                    "minimum_commitment",
                    f"Minimum commitment true-up{suffix}",
                    floor - usage_spend,
                    fraction,
                )
            )
    return lines


def _fixed_line(
    phase: PhaseSnapshot,
    charge: Charge,
    model: FlatPrice,
    fraction: Decimal,
    currency: Currency,
    suffix: str,
) -> ComputedLine:
    exact = model.amount * fraction
    return ComputedLine(
        key=_key(phase, charge.key, LineKind.FIXED),
        kind=LineKind.FIXED,
        charge_key=charge.key,
        description=f"{phase.plan_name} · {charge.name}{suffix}",
        metric_code=None,
        plan_version_id=phase.plan_version_id,
        phase_start=phase.start,
        phase_end=phase.end,
        proration=fraction,
        quantity=Decimal(1),
        billable_quantity=fraction,
        exact=exact,
        amount=Money.of(exact, currency),
    )


def _usage_line(
    phase: PhaseSnapshot,
    charge: Charge,
    metric_code: str,
    model: UsagePriceModel,
    fraction: Decimal,
    currency: Currency,
    suffix: str,
) -> ComputedLine:
    usage = phase.usage.get(metric_code, MetricUsage(total=Decimal(0)))
    if fraction != 1 and model.free_units:
        model = model.model_copy(update={"free_units": model.free_units * fraction})

    priced = price(model, usage.total, currency)
    shares = allocate(priced.amount, [g.quantity for g in usage.groups])
    groups = tuple(
        AllocatedGroup(dimensions=g.dimensions, quantity=g.quantity, amount=share)
        for g, share in zip(usage.groups, shares, strict=True)
    )
    return ComputedLine(
        key=_key(phase, charge.key, LineKind.USAGE),
        kind=LineKind.USAGE,
        charge_key=charge.key,
        description=f"{charge.name}{suffix}",
        metric_code=metric_code,
        plan_version_id=phase.plan_version_id,
        phase_start=phase.start,
        phase_end=phase.end,
        proration=fraction,
        quantity=priced.quantity,
        billable_quantity=priced.billable_quantity,
        exact=priced.exact,
        amount=priced.amount,
        components=priced.components,
        groups=groups,
    )


def _minimum_line(
    phase: PhaseSnapshot, charge_key: str, description: str, amount: Money, fraction: Decimal
) -> ComputedLine:
    return ComputedLine(
        key=_key(phase, charge_key, LineKind.MINIMUM),
        kind=LineKind.MINIMUM,
        charge_key=charge_key,
        description=description,
        metric_code=None,
        plan_version_id=phase.plan_version_id,
        phase_start=phase.start,
        phase_end=phase.end,
        proration=fraction,
        quantity=Decimal(1),
        billable_quantity=Decimal(1),
        exact=amount.amount,
        amount=amount,
    )


def _key(phase: PhaseSnapshot, charge_key: str, kind: LineKind) -> str:
    return f"{phase.start.isoformat()}:{charge_key}:{kind.value}"
