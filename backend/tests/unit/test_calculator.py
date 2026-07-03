from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meterly.billing.calculator import (
    ChargeKindMismatchError,
    LineKind,
    PhaseSnapshot,
    UsageSnapshot,
    compute_lines,
    subtotal,
)
from meterly.billing.rerate import diff_lines
from meterly.billing.terms import Charge, PlanTerms
from meterly.metering.usage import GroupUsage, MetricUsage
from meterly.money import Currency, Money
from meterly.pricing import FlatPrice, GraduatedPrice, PerUnitPrice, Tier, price

USD = Currency.USD
APRIL = (date(2026, 4, 1), date(2026, 5, 1))


def _terms(platform_fee: str = "49", unit: str = "0.002", minimum: str | None = None) -> PlanTerms:
    return PlanTerms(
        currency=USD,
        minimum_commitment=Decimal(minimum) if minimum else None,
        charges=[
            Charge(
                key="platform", name="Platform fee", price=FlatPrice(amount=Decimal(platform_fee))
            ),
            Charge(
                key="api_calls",
                name="API calls",
                metric_code="api_calls",
                price=PerUnitPrice(unit_price=Decimal(unit), free_units=Decimal(10000)),
            ),
        ],
    )


def _phase(
    terms: PlanTerms, start: date, end: date, calls: str, name: str = "Growth"
) -> PhaseSnapshot:
    return PhaseSnapshot(
        plan_version_id=uuid4(),
        plan_name=name,
        version=1,
        terms=terms,
        start=start,
        end=end,
        usage={"api_calls": MetricUsage(total=Decimal(calls))},
    )


def test_full_period_invoice() -> None:
    snapshot = UsageSnapshot(
        period_start=APRIL[0],
        period_end=APRIL[1],
        currency=USD,
        phases=[_phase(_terms(), *APRIL, calls="60000")],
    )
    lines = compute_lines(snapshot)
    assert [line.amount for line in lines] == [Money.of("49", USD), Money.of("100", USD)]


def test_mid_cycle_upgrade_prorates_by_day() -> None:
    switch = date(2026, 4, 11)
    snapshot = UsageSnapshot(
        period_start=APRIL[0],
        period_end=APRIL[1],
        currency=USD,
        phases=[
            _phase(_terms("30"), APRIL[0], switch, calls="5000", name="Starter"),
            _phase(_terms("90"), switch, APRIL[1], calls="40000", name="Scale"),
        ],
    )
    lines = compute_lines(snapshot)
    fixed = [line for line in lines if line.kind is LineKind.FIXED]
    assert [line.amount for line in fixed] == [Money.of("10", USD), Money.of("60", USD)]
    usage = [line for line in lines if line.kind is LineKind.USAGE]
    # free allowance is prorated too: 10000 * 20/30 = 6666.67 free units in the second phase
    assert usage[1].billable_quantity.quantize(Decimal("0.01")) == Decimal("33333.33")


def test_minimum_commitment_true_up() -> None:
    snapshot = UsageSnapshot(
        period_start=APRIL[0],
        period_end=APRIL[1],
        currency=USD,
        phases=[_phase(_terms(minimum="250"), *APRIL, calls="60000")],
    )
    lines = compute_lines(snapshot)
    true_up = lines[-1]
    assert true_up.kind is LineKind.MINIMUM
    assert true_up.amount == Money.of("150", USD)
    assert subtotal(lines, USD) == Money.of("299", USD)


def test_group_breakdown_reconciles_to_line() -> None:
    phase = _phase(_terms(unit="0.0003"), *APRIL, calls="0").model_copy(
        update={
            "usage": {
                "api_calls": MetricUsage(
                    total=Decimal(43333),
                    groups=[
                        GroupUsage(dimensions={"region": r}, quantity=Decimal(q))
                        for r, q in [("us", 14444), ("eu", 14444), ("ap", 14445)]
                    ],
                )
            }
        }
    )
    snapshot = UsageSnapshot(
        period_start=APRIL[0], period_end=APRIL[1], currency=USD, phases=[phase]
    )
    usage = compute_lines(snapshot)[1]
    assert Money.total((g.amount for g in usage.groups), USD) == usage.amount


def test_rerate_diff() -> None:
    snapshot = UsageSnapshot(
        period_start=APRIL[0],
        period_end=APRIL[1],
        currency=USD,
        phases=[_phase(_terms(), *APRIL, calls="60000")],
    )
    before = compute_lines(snapshot)
    after = compute_lines(snapshot, {"api_calls": PerUnitPrice(unit_price=Decimal("0.001"))})
    diff = diff_lines(before, after, USD)
    assert diff.delta == Money.of("-40", USD)
    assert diff.lines[1].after == Money.of("60", USD)


graduated = GraduatedPrice(
    tiers=[
        Tier(up_to=Decimal(1000), unit_price=Decimal("0.0137")),
        Tier(up_to=Decimal(50000), unit_price=Decimal("0.00733"), flat_fee=Decimal("1.11")),
        Tier(up_to=None, unit_price=Decimal("0.000999")),
    ]
)


@settings(max_examples=150)
@given(
    st.lists(st.integers(min_value=0, max_value=5_000_000), min_size=1, max_size=4),
    st.integers(min_value=1, max_value=29),
)
def test_invoice_lines_always_reconcile(volumes: list[int], split_day: int) -> None:
    terms = PlanTerms(
        currency=USD,
        minimum_commitment=Decimal("75.55"),
        charges=[
            Charge(key="base", name="Base", price=FlatPrice(amount=Decimal("19.99"))),
            Charge(key="calls", name="Calls", metric_code="calls", price=graduated),
        ],
    )
    split = date(2026, 4, split_day + 1)
    phases = []
    for start, end in [(APRIL[0], split), (split, APRIL[1])]:
        groups = [
            GroupUsage(dimensions={"g": str(i)}, quantity=Decimal(v)) for i, v in enumerate(volumes)
        ]
        phases.append(
            PhaseSnapshot(
                plan_version_id=uuid4(),
                plan_name="P",
                version=1,
                terms=terms,
                start=start,
                end=end,
                usage={"calls": MetricUsage(total=Decimal(sum(volumes)), groups=groups)},
            )
        )
    snapshot = UsageSnapshot(
        period_start=APRIL[0], period_end=APRIL[1], currency=USD, phases=phases
    )
    lines = compute_lines(snapshot)

    for line in lines:
        assert line.amount == Money.of(line.exact, USD)
        if line.components:
            assert Money.total((c.amount for c in line.components), USD) == line.amount
        if line.groups:
            assert Money.total((g.amount for g in line.groups), USD) == line.amount
    for phase in phases:
        phase_spend = Money.total(
            (
                ln.amount
                for ln in lines
                if ln.phase_start == phase.start and ln.kind is not LineKind.FIXED
            ),
            USD,
        )
        floor = Money.of(Decimal("75.55") * phase.window.fraction_of(snapshot.period), USD)
        assert phase_spend >= floor
    fixed_total = Money.total((ln.amount for ln in lines if ln.kind is LineKind.FIXED), USD)
    assert abs(fixed_total.amount - Decimal("19.99")) <= Decimal("0.01")


@pytest.mark.parametrize(
    "overrides",
    [
        {"platform": PerUnitPrice(unit_price=Decimal(1))},
        {"api_calls": FlatPrice(amount=Decimal(10))},
    ],
)
def test_override_must_keep_the_charge_kind(overrides: dict[str, FlatPrice | PerUnitPrice]) -> None:
    snapshot = UsageSnapshot(
        period_start=APRIL[0],
        period_end=APRIL[1],
        currency=USD,
        phases=[_phase(_terms(), *APRIL, calls="20000")],
    )
    with pytest.raises(ChargeKindMismatchError):
        compute_lines(snapshot, overrides)


def test_huge_quantities_are_priced_without_early_rounding() -> None:
    quantity = Decimal("12345678901234567890.1234567891")
    unit_price = Decimal("0.0000000123")
    priced = price(PerUnitPrice(unit_price=unit_price), quantity, USD)
    assert priced.exact == Decimal("151851850485.18518504851851850593")
    assert priced.amount.amount == Decimal("151851850485.19")
