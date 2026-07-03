from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.calculator import PhaseSnapshot, UsageSnapshot
from meterly.billing.mappers import terms_of
from meterly.billing.periods import Interval, Period, period_containing
from meterly.billing.terms import PlanTerms
from meterly.db.models import Subscription
from meterly.errors import InvalidRequestError
from meterly.metering.repository import MetricRepository, UsageRepository
from meterly.metering.usage import MetricUsage
from meterly.money import Currency

CANDIDATE_VERSION_ID = UUID(int=0)


def bill_window(sub: Subscription) -> Period:
    """The not-yet-invoiced slice of the subscription's current period."""
    period = period_containing(sub.billing_anchor, Interval(sub.interval), sub.billed_through)
    end = period.end if sub.ends_on is None else min(period.end, sub.ends_on)
    return Period(sub.billed_through, max(end, sub.billed_through))


def next_period_end(sub: Subscription) -> date:
    period = period_containing(sub.billing_anchor, Interval(sub.interval), sub.billed_through)
    return period.end if sub.ends_on is None else min(period.end, sub.ends_on)


class SnapshotBuilder:
    def __init__(self, session: AsyncSession) -> None:
        self._metrics = MetricRepository(session)
        self._usage = UsageRepository(session)

    async def for_subscription(self, sub: Subscription, window: Period) -> UsageSnapshot:
        full = period_containing(sub.billing_anchor, Interval(sub.interval), window.start)
        currency = Currency(sub.customer.currency)
        phases: list[PhaseSnapshot] = []
        for phase in sorted(sub.phases, key=lambda p: p.starts_on):
            span = Period(phase.starts_on, phase.ends_on or date.max)
            overlap = span.intersect(window)
            if overlap is None:
                continue
            if sub.trial_ends_on is not None:
                overlap = overlap.intersect(Period(sub.trial_ends_on, date.max))
                if overlap is None:
                    continue
            version = phase.plan_version
            terms = terms_of(version)
            usage = await self._usage_for(terms, sub, overlap)
            phases.append(
                PhaseSnapshot(
                    plan_version_id=version.id,
                    plan_name=version.plan.name,
                    version=version.version,
                    terms=terms,
                    start=overlap.start,
                    end=overlap.end,
                    usage=usage,
                )
            )
        return UsageSnapshot(
            period_start=full.start, period_end=full.end, currency=currency, phases=phases
        )

    async def with_terms(
        self, sub: Subscription, window: Period, terms: PlanTerms, label: str
    ) -> UsageSnapshot:
        """Price an arbitrary candidate plan against the subscription's real usage."""
        full = period_containing(sub.billing_anchor, Interval(sub.interval), window.start)
        currency = Currency(sub.customer.currency)
        if terms.currency is not currency:
            raise InvalidRequestError(
                f"candidate plan is priced in {terms.currency}, customer pays in {currency}"
            )
        usage = await self._usage_for(terms, sub, window)
        phase = PhaseSnapshot(
            plan_version_id=CANDIDATE_VERSION_ID,
            plan_name=label,
            version=0,
            terms=terms,
            start=window.start,
            end=window.end,
            usage=usage,
        )
        return UsageSnapshot(
            period_start=full.start, period_end=full.end, currency=currency, phases=[phase]
        )

    async def _usage_for(
        self, terms: PlanTerms, sub: Subscription, window: Period
    ) -> dict[str, MetricUsage]:
        codes = sorted({c.metric_code for c in terms.charges if c.metric_code})
        metrics = await self._metrics.by_codes(codes)
        missing = set(codes) - metrics.keys()
        if missing:
            raise InvalidRequestError(f"plan references unknown metrics: {sorted(missing)}")
        result: dict[str, MetricUsage] = {}
        for code in codes:
            result[code] = await self._usage.usage(
                metrics[code], sub.customer_id, window.starts_at, window.ends_at
            )
        return result
