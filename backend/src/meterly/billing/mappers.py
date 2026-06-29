from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import TypeAdapter

from meterly.billing.calculator import LineKind, UsageSnapshot
from meterly.billing.periods import Interval, period_containing
from meterly.billing.schemas import (
    InvoiceLineOut,
    InvoiceOut,
    InvoiceSummary,
    LineDetails,
    PhaseOut,
    PlanOut,
    PlanVersionOut,
    SubscriptionOut,
)
from meterly.billing.statuses import InvoiceStatus, SubscriptionStatus
from meterly.billing.terms import Charge, PlanTerms
from meterly.db.models import Invoice, Plan, PlanVersion, Subscription, SubscriptionPhase
from meterly.money import Currency, Money
from meterly.pricing import PriceModel

OverridesAdapter: TypeAdapter[dict[str, PriceModel]] = TypeAdapter(dict[str, PriceModel])


def price_overrides(invoice: Invoice) -> dict[str, PriceModel]:
    return OverridesAdapter.validate_python(invoice.price_overrides)


def dump_overrides(overrides: dict[str, PriceModel]) -> dict[str, object]:
    dumped: dict[str, object] = OverridesAdapter.dump_python(overrides, mode="json")
    return dumped


def terms_of(version: PlanVersion) -> PlanTerms:
    return PlanTerms.model_validate(version.terms)


def plan_version_out(version: PlanVersion) -> PlanVersionOut:
    terms = terms_of(version)
    return PlanVersionOut(
        id=version.id,
        version=version.version,
        created_at=version.created_at,
        terms=terms,
        fixed_amount=Money.of(terms.fixed_amount(), terms.currency),
    )


def plan_out(plan: Plan) -> PlanOut:
    return PlanOut(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        description=plan.description,
        versions=[plan_version_out(v) for v in sorted(plan.versions, key=lambda v: -v.version)],
    )


def subscription_status(sub: Subscription, today: date) -> SubscriptionStatus:
    if sub.ends_on is not None and sub.ends_on <= today:
        return SubscriptionStatus.CANCELED
    if sub.started_on > today:
        return SubscriptionStatus.SCHEDULED
    if sub.trial_ends_on is not None and today < sub.trial_ends_on:
        return SubscriptionStatus.TRIALING
    return SubscriptionStatus.ACTIVE


def current_phase(sub: Subscription, day: date) -> SubscriptionPhase:
    for phase in sorted(sub.phases, key=lambda p: p.starts_on, reverse=True):
        if phase.starts_on <= day:
            return phase
    return sub.phases[0]


def subscription_out(sub: Subscription, today: date) -> SubscriptionOut:
    period = period_containing(sub.billing_anchor, Interval(sub.interval), sub.billed_through)
    return SubscriptionOut(
        id=sub.id,
        customer_id=sub.customer.external_id,
        status=subscription_status(sub, today),
        interval=Interval(sub.interval),
        billing_anchor=sub.billing_anchor,
        started_on=sub.started_on,
        trial_ends_on=sub.trial_ends_on,
        ends_on=sub.ends_on,
        billed_through=sub.billed_through,
        current_period_start=max(period.start, sub.billed_through),
        current_period_end=sub.current_period_end,
        phases=[
            PhaseOut(
                plan_version_id=p.plan_version_id,
                plan_code=p.plan_version.plan.code,
                plan_name=p.plan_version.plan.name,
                version=p.plan_version.version,
                starts_on=p.starts_on,
                ends_on=p.ends_on,
            )
            for p in sorted(sub.phases, key=lambda p: p.starts_on)
        ],
    )


def money(amount: Decimal, currency: str) -> Money:
    return Money.of(amount, Currency(currency))


def invoice_summary(invoice: Invoice) -> InvoiceSummary:
    return InvoiceSummary(
        id=invoice.id,
        number=invoice.number,
        status=InvoiceStatus(invoice.status),
        customer_id=invoice.customer.external_id,
        customer_name=invoice.customer.name,
        currency=Currency(invoice.currency),
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        total=money(invoice.total, invoice.currency),
        created_at=invoice.created_at,
        finalized_at=invoice.finalized_at,
    )


def invoice_charges(invoice: Invoice) -> list[Charge]:
    """The charges an invoice was priced with, including any re-rating overrides."""
    snapshot = UsageSnapshot.model_validate(invoice.usage_snapshot)
    charges: dict[str, Charge] = {}
    for phase in snapshot.phases:
        for charge in phase.terms.charges:
            charges[charge.key] = charge
    overrides = price_overrides(invoice)
    return [
        charge.model_copy(update={"price": overrides[key]}) if key in overrides else charge
        for key, charge in charges.items()
    ]


def invoice_out(invoice: Invoice) -> InvoiceOut:
    summary = invoice_summary(invoice)
    return InvoiceOut(
        **summary.model_dump(),
        subtotal=money(invoice.subtotal, invoice.currency),
        price_overrides=price_overrides(invoice),
        charges=invoice_charges(invoice),
        lines=[
            InvoiceLineOut(
                key=line.line_key,
                kind=LineKind(line.kind),
                charge_key=line.charge_key,
                description=line.description,
                metric_code=line.metric_code,
                phase_start=line.phase_start,
                phase_end=line.phase_end,
                quantity=line.quantity,
                billable_quantity=line.billable_quantity,
                amount=money(line.amount, invoice.currency),
                details=LineDetails.model_validate(line.details),
            )
            for line in invoice.lines
        ],
    )
