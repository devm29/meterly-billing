from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.calculator import compute_lines, subtotal
from meterly.billing.mappers import current_phase, money, terms_of
from meterly.billing.periods import Period
from meterly.billing.repository import (
    CustomerRepository,
    InvoiceRepository,
    PlanRepository,
    SubscriptionRepository,
)
from meterly.billing.schemas import InvoiceLineOut
from meterly.billing.snapshots import SnapshotBuilder, bill_window
from meterly.billing.terms import PlanTerms
from meterly.errors import InvalidRequestError, NotFoundError
from meterly.money import Currency, Money


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    plan_version_id: UUID | None = None
    terms: PlanTerms | None = None
    periods: Annotated[int, Field(ge=1, le=12)] = 3

    @model_validator(mode="after")
    def _one_candidate(self) -> SimulationRequest:
        if (self.plan_version_id is None) == (self.terms is None):
            raise ValueError("provide exactly one of plan_version_id or terms")
        return self


class SimulatedPeriod(BaseModel):
    period_start: date
    period_end: date
    in_progress: bool
    actual: Money
    candidate: Money
    delta: Money
    candidate_lines: list[InvoiceLineOut]


class SimulationOut(BaseModel):
    customer_id: str
    currency: Currency
    current_plan: str
    candidate_plan: str
    periods: list[SimulatedPeriod]
    total_actual: Money
    total_candidate: Money
    delta: Money
    delta_ratio: Decimal | None


def utc_now() -> datetime:
    return datetime.now(UTC)


class PricingSimulator:
    """Replays a customer's real metered usage through a candidate plan."""

    def __init__(self, session: AsyncSession, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock
        self._customers = CustomerRepository(session)
        self._subs = SubscriptionRepository(session)
        self._invoices = InvoiceRepository(session)
        self._plans = PlanRepository(session)
        self._snapshots = SnapshotBuilder(session)

    async def simulate(self, request: SimulationRequest) -> SimulationOut:
        customer = await self._customers.get_by_external_id(request.customer_id)
        if customer is None:
            raise NotFoundError(f"customer {request.customer_id!r} does not exist")
        sub = await self._subs.latest_for_customer(customer.id)
        if sub is None:
            raise InvalidRequestError("customer has no subscription to compare against")

        terms, label = await self._candidate(request)
        currency = Currency(customer.currency)
        today = self._clock().astimezone(UTC).date()
        current_label = current_phase(sub, today).plan_version.plan.name

        windows: list[tuple[Period, Money, bool]] = []
        history = await self._invoices.recent_for_subscription(sub.id, request.periods)
        for invoice in reversed(history):
            windows.append(
                (
                    Period(invoice.period_start, invoice.period_end),
                    money(invoice.total, invoice.currency),
                    False,
                )
            )
        live = bill_window(sub)
        if not live.is_empty and live.start <= today:
            actual_snapshot = await self._snapshots.for_subscription(sub, live)
            windows.append((live, subtotal(compute_lines(actual_snapshot), currency), True))

        periods: list[SimulatedPeriod] = []
        for window, actual, in_progress in windows:
            snapshot = await self._snapshots.with_terms(sub, window, terms, label)
            lines = compute_lines(snapshot)
            candidate = subtotal(lines, currency)
            periods.append(
                SimulatedPeriod(
                    period_start=window.start,
                    period_end=window.end,
                    in_progress=in_progress,
                    actual=actual,
                    candidate=candidate,
                    delta=candidate - actual,
                    candidate_lines=[InvoiceLineOut.from_computed(line) for line in lines],
                )
            )

        total_actual = Money.total((p.actual for p in periods), currency)
        total_candidate = Money.total((p.candidate for p in periods), currency)
        delta = total_candidate - total_actual
        return SimulationOut(
            customer_id=request.customer_id,
            currency=currency,
            current_plan=current_label,
            candidate_plan=label,
            periods=periods,
            total_actual=total_actual,
            total_candidate=total_candidate,
            delta=delta,
            delta_ratio=(delta.amount / total_actual.amount).quantize(Decimal("0.0001"))
            if total_actual.amount
            else None,
        )

    async def _candidate(self, request: SimulationRequest) -> tuple[PlanTerms, str]:
        if request.terms is not None:
            return request.terms, "Custom pricing"
        assert request.plan_version_id is not None
        version = await self._plans.get_version(request.plan_version_id)
        if version is None:
            raise NotFoundError(f"plan version {request.plan_version_id} does not exist")
        return terms_of(version), f"{version.plan.name} v{version.version}"
