from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from meterly.billing.calculator import AllocatedGroup, ComputedLine, LineKind
from meterly.billing.periods import Interval
from meterly.billing.rerate import RerateDiff
from meterly.billing.statuses import InvoiceStatus, SubscriptionStatus
from meterly.billing.terms import Charge, PlanTerms
from meterly.money import Currency, Money
from meterly.pricing import PriceComponent, PriceModel
from meterly.types import Slug


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Slug
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=500)] | None = None
    terms: PlanTerms


class PlanVersionOut(BaseModel):
    id: UUID
    version: int
    created_at: datetime
    terms: PlanTerms
    fixed_amount: Money


class PlanOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    versions: list[PlanVersionOut]


class SubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: Annotated[str, Field(description="Customer external id")]
    plan_code: Slug | None = None
    plan_version_id: UUID | None = None
    start_on: date | None = None
    billing_anchor: date | None = None
    trial_days: Annotated[int, Field(ge=0, le=365)] | None = None


class PlanChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_version_id: UUID
    effective_on: date | None = None
    dry_run: bool = False


class Cancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_on: date | None = None


class PhaseOut(BaseModel):
    plan_version_id: UUID
    plan_code: str
    plan_name: str
    version: int
    starts_on: date
    ends_on: date | None


class SubscriptionOut(BaseModel):
    id: UUID
    customer_id: str
    status: SubscriptionStatus
    interval: Interval
    billing_anchor: date
    started_on: date
    trial_ends_on: date | None
    ends_on: date | None
    billed_through: date
    current_period_start: date
    current_period_end: date
    phases: list[PhaseOut]


class ProrationPreview(BaseModel):
    effective_on: date
    period_start: date
    period_end: date
    days_remaining: int
    days_in_period: int
    old_fixed_for_remaining_days: Money
    new_fixed_for_remaining_days: Money
    net_change: Money


class PlanChangeOut(BaseModel):
    applied: bool
    proration: ProrationPreview
    subscription: SubscriptionOut


class LineDetails(BaseModel):
    """How a line was priced: the unrounded amount, proration and its breakdowns."""

    model_config = ConfigDict(frozen=True)

    exact: Decimal
    proration: Decimal
    components: list[PriceComponent] = []
    groups: list[AllocatedGroup] = []

    @classmethod
    def of(cls, line: ComputedLine) -> LineDetails:
        return cls(
            exact=line.exact,
            proration=line.proration,
            components=list(line.components),
            groups=list(line.groups),
        )


class InvoiceLineOut(BaseModel):
    key: str
    kind: LineKind
    charge_key: str
    description: str
    metric_code: str | None
    phase_start: date
    phase_end: date
    quantity: Decimal
    billable_quantity: Decimal
    amount: Money
    details: LineDetails

    @classmethod
    def from_computed(cls, line: ComputedLine) -> InvoiceLineOut:
        return cls(
            key=line.key,
            kind=line.kind,
            charge_key=line.charge_key,
            description=line.description,
            metric_code=line.metric_code,
            phase_start=line.phase_start,
            phase_end=line.phase_end,
            quantity=line.quantity,
            billable_quantity=line.billable_quantity,
            amount=line.amount,
            details=LineDetails.of(line),
        )


class InvoiceSummary(BaseModel):
    id: UUID
    number: str | None
    status: InvoiceStatus
    customer_id: str
    customer_name: str
    currency: Currency
    period_start: date
    period_end: date
    total: Money
    created_at: datetime
    finalized_at: datetime | None


class InvoiceOut(InvoiceSummary):
    subtotal: Money
    lines: list[InvoiceLineOut]
    price_overrides: dict[str, PriceModel]
    charges: list[Charge]


class UpcomingInvoiceOut(BaseModel):
    subscription_id: UUID
    currency: Currency
    period_start: date
    period_end: date
    as_of: datetime
    lines: list[InvoiceLineOut]
    subtotal: Money


class RerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: Annotated[dict[str, PriceModel], Field(min_length=1)]
    apply: bool = False


class RerateOut(BaseModel):
    applied: bool
    diff: RerateDiff


class CloseRunOut(BaseModel):
    drafted: list[UUID]
    finalized: list[UUID]
    failed_subscriptions: list[UUID] = []
    failed_invoices: list[UUID] = []
