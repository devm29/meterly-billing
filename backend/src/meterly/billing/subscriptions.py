from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.calculator import compute_lines, subtotal
from meterly.billing.mappers import current_phase, subscription_out, terms_of
from meterly.billing.periods import Interval, Period, period_containing
from meterly.billing.repository import CustomerRepository, PlanRepository, SubscriptionRepository
from meterly.billing.schemas import (
    Cancellation,
    InvoiceLineOut,
    PlanChange,
    PlanChangeOut,
    ProrationPreview,
    SubscriptionCreate,
    SubscriptionOut,
    UpcomingInvoiceOut,
)
from meterly.billing.snapshots import SnapshotBuilder, bill_window
from meterly.db.models import PlanVersion, Subscription, SubscriptionPhase
from meterly.errors import ConflictError, InvalidRequestError, NotFoundError
from meterly.money import Currency, Money


def utc_now() -> datetime:
    return datetime.now(UTC)


class CacheInvalidator(Protocol):
    async def invalidate(self, customer_ids: Sequence[UUID]) -> None: ...


class SubscriptionService:
    def __init__(
        self,
        session: AsyncSession,
        invalidator: CacheInvalidator,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._invalidator = invalidator
        self._clock = clock
        self._subs = SubscriptionRepository(session)
        self._plans = PlanRepository(session)
        self._customers = CustomerRepository(session)
        self._snapshots = SnapshotBuilder(session)

    def _today(self) -> date:
        return self._clock().astimezone(UTC).date()

    async def get(self, subscription_id: UUID) -> SubscriptionOut:
        return subscription_out(await self._load(subscription_id), self._today())

    async def create(self, payload: SubscriptionCreate) -> SubscriptionOut:
        customer = await self._customers.get_by_external_id(payload.customer_id)
        if customer is None:
            raise NotFoundError(f"customer {payload.customer_id!r} does not exist")
        version = await self._resolve_version(payload.plan_code, payload.plan_version_id)
        terms = terms_of(version)
        if terms.currency != customer.currency:
            raise InvalidRequestError(
                f"plan is priced in {terms.currency}, customer pays in {customer.currency}"
            )

        start = payload.start_on or self._today()
        anchor = payload.billing_anchor or start
        if anchor > start:
            raise InvalidRequestError("billing_anchor cannot be after start_on")
        trial_days = terms.trial_days if payload.trial_days is None else payload.trial_days
        period = period_containing(anchor, terms.interval, start)
        overlapping = await self._subs.overlapping(customer.id, start)
        if overlapping is not None:
            until = overlapping.ends_on.isoformat() if overlapping.ends_on else "open-ended"
            raise ConflictError(
                f"customer {payload.customer_id!r} already has a subscription covering {start} "
                f"(runs until {until})"
            )

        sub = Subscription(
            customer_id=customer.id,
            billing_anchor=anchor,
            interval=terms.interval.value,
            started_on=start,
            trial_ends_on=start + timedelta(days=trial_days) if trial_days else None,
            billed_through=start,
            current_period_end=period.end,
        )
        sub.phases = [SubscriptionPhase(plan_version_id=version.id, starts_on=start)]
        self._session.add(sub)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            # Lost a race with a concurrent create; the exclusion constraint caught it.
            await self._session.rollback()
            raise ConflictError(
                f"customer {payload.customer_id!r} already has an overlapping subscription"
            ) from exc
        await self._invalidator.invalidate([customer.id])
        return await self.get(sub.id)

    async def change_plan(self, subscription_id: UUID, change: PlanChange) -> PlanChangeOut:
        sub = await self._load(subscription_id, lock=not change.dry_run)
        today = self._today()
        effective = change.effective_on or today
        if sub.ends_on is not None and sub.ends_on <= effective:
            raise ConflictError("subscription has ended")
        if effective < sub.billed_through:
            raise InvalidRequestError(
                f"{effective} falls in an invoiced period; changes must be on or after "
                f"{sub.billed_through}"
            )
        if effective >= sub.current_period_end:
            raise InvalidRequestError(
                "plan changes apply within the current period; schedule it on or before "
                f"{sub.current_period_end - timedelta(days=1)}"
            )

        new_version = await self._resolve_version(None, change.plan_version_id)
        new_terms = terms_of(new_version)
        phase = current_phase(sub, effective)
        old_terms = terms_of(phase.plan_version)
        if new_terms.currency is not old_terms.currency:
            raise InvalidRequestError("cannot switch to a plan in a different currency")
        if new_terms.interval is not old_terms.interval:
            raise InvalidRequestError("cannot switch billing interval mid-subscription")
        scheduled_later = any(p.starts_on > effective for p in sub.phases)
        if phase.plan_version_id == new_version.id and not scheduled_later:
            raise ConflictError("subscription is already on that plan version")

        period = period_containing(sub.billing_anchor, Interval(sub.interval), effective)
        preview = _proration(
            period,
            effective,
            old_terms.fixed_amount(),
            new_terms.fixed_amount(),
            old_terms.currency,
        )

        if not change.dry_run:
            await self._reschedule(sub, phase, new_version, effective)
            await self._session.commit()
            await self._invalidator.invalidate([sub.customer_id])
            self._session.expire_all()
            sub = await self._load(subscription_id)
        return PlanChangeOut(
            applied=not change.dry_run,
            proration=preview,
            subscription=subscription_out(sub, today),
        )

    async def cancel(self, subscription_id: UUID, cancellation: Cancellation) -> SubscriptionOut:
        sub = await self._load(subscription_id, lock=True)
        effective = cancellation.effective_on or sub.current_period_end
        if sub.ends_on is not None:
            raise ConflictError(f"subscription already ends on {sub.ends_on}")
        if effective < sub.billed_through or effective <= sub.started_on:
            raise InvalidRequestError(f"cancellation must be after {sub.billed_through}")
        sub.ends_on = effective
        sub.current_period_end = min(sub.current_period_end, effective)
        for phase in sub.phases:
            if phase.starts_on >= effective:
                await self._session.delete(phase)
            elif phase.ends_on is None or phase.ends_on > effective:
                phase.ends_on = effective
        await self._session.commit()
        await self._invalidator.invalidate([sub.customer_id])
        self._session.expire_all()
        return await self.get(subscription_id)

    async def upcoming_invoice(self, subscription_id: UUID) -> UpcomingInvoiceOut:
        sub = await self._load(subscription_id)
        window = bill_window(sub)
        snapshot = await self._snapshots.for_subscription(sub, window)
        lines = compute_lines(snapshot)
        return UpcomingInvoiceOut(
            subscription_id=sub.id,
            currency=snapshot.currency,
            period_start=window.start,
            period_end=window.end,
            as_of=self._clock(),
            lines=[InvoiceLineOut.from_computed(line) for line in lines],
            subtotal=subtotal(lines, snapshot.currency),
        )

    async def _reschedule(
        self,
        sub: Subscription,
        phase: SubscriptionPhase,
        version: PlanVersion,
        effective: date,
    ) -> None:
        """Switch to ``version`` from ``effective`` on, replacing any change scheduled later.

        Phases must tile the subscription without gaps or overlaps (enforced by an exclusion
        constraint); a later scheduled phase left in place would bill its days twice.
        """
        for later in [p for p in sub.phases if p.starts_on > effective]:
            sub.phases.remove(later)
            await self._session.delete(later)
        await self._session.flush()
        if phase.starts_on == effective or phase.plan_version_id == version.id:
            phase.plan_version_id = version.id
            phase.ends_on = sub.ends_on
            return
        phase.ends_on = effective
        sub.phases.append(
            SubscriptionPhase(
                subscription_id=sub.id,
                plan_version_id=version.id,
                starts_on=effective,
                ends_on=sub.ends_on,
            )
        )

    async def _load(self, subscription_id: UUID, *, lock: bool = False) -> Subscription:
        sub = await self._subs.get(subscription_id, lock=lock)
        if sub is None:
            raise NotFoundError(f"subscription {subscription_id} does not exist")
        return sub

    async def _resolve_version(self, plan_code: str | None, version_id: UUID | None) -> PlanVersion:
        if version_id is not None:
            version = await self._plans.get_version(version_id)
            if version is None:
                raise NotFoundError(f"plan version {version_id} does not exist")
            return version
        if plan_code is None:
            raise InvalidRequestError("provide plan_code or plan_version_id")
        plan = await self._plans.get_by_code(plan_code)
        if plan is None or not plan.versions:
            raise NotFoundError(f"plan {plan_code!r} does not exist")
        latest = max(plan.versions, key=lambda v: v.version)
        return await self._resolve_version(None, latest.id)


def _proration(
    period: Period, effective: date, old_fixed: Decimal, new_fixed: Decimal, currency: Currency
) -> ProrationPreview:
    """Fixed fees are billed in arrears, so a switch swaps which fee covers the remaining days."""
    remaining = Period(effective, period.end)
    factor = remaining.fraction_of(period)
    old = Money.of(old_fixed * factor, currency)
    new = Money.of(new_fixed * factor, currency)
    return ProrationPreview(
        effective_on=effective,
        period_start=period.start,
        period_end=period.end,
        days_remaining=remaining.days,
        days_in_period=period.days,
        old_fixed_for_remaining_days=old,
        new_fixed_for_remaining_days=new,
        net_change=new - old,
    )
