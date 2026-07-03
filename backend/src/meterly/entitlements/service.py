from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.mappers import current_phase, terms_of
from meterly.billing.periods import Interval, period_containing
from meterly.billing.repository import CustomerRepository, SubscriptionRepository
from meterly.billing.terms import FeatureEntitlement
from meterly.config import Settings
from meterly.db.models import Subscription
from meterly.entitlements.cache import EntitlementCache
from meterly.errors import NotFoundError
from meterly.metering.definitions import Metric
from meterly.metering.repository import MetricRepository, UsageRepository


class EntitlementOut(BaseModel):
    feature: str
    name: str
    allowed: bool
    reason: str
    metric_code: str | None
    limit: Decimal | None
    used: Decimal | None
    remaining: Decimal | None
    period_start: date | None
    period_end: date | None
    plan_code: str | None
    cached: bool = False


class EntitlementsOut(BaseModel):
    customer_id: str
    entitlements: list[EntitlementOut]


def utc_now() -> datetime:
    return datetime.now(UTC)


class EntitlementService:
    """Answers "may this customer use X right now, and how much is left?" from rollups."""

    def __init__(
        self,
        session: AsyncSession,
        cache: EntitlementCache,
        settings: Settings,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._cache = cache
        self._settings = settings
        self._clock = clock
        self._customers = CustomerRepository(session)
        self._subs = SubscriptionRepository(session)
        self._metrics = MetricRepository(session)
        self._usage = UsageRepository(session)

    async def check(self, customer_external_id: str, feature: str) -> EntitlementOut:
        customer_id = await self._customer_id(customer_external_id)
        today = self._clock().astimezone(UTC).date()
        cached = await self._cached(customer_id, feature, today)
        if cached is not None:
            return cached
        sub = await self._subs.live_for_customer(customer_id, today)
        return await self._store(customer_id, today, await self._resolve(sub, feature, today))

    async def all_for(self, customer_external_id: str) -> EntitlementsOut:
        """Every feature of the current plan, resolving the subscription and metrics once."""
        customer_id = await self._customer_id(customer_external_id)
        today = self._clock().astimezone(UTC).date()
        sub = await self._subs.live_for_customer(customer_id, today)
        if sub is None:
            return EntitlementsOut(customer_id=customer_external_id, entitlements=[])
        terms = terms_of(current_phase(sub, today).plan_version)
        metrics = await self._metrics.by_codes(
            sorted({e.metric_code for e in terms.entitlements if e.metric_code})
        )
        results: list[EntitlementOut] = []
        for spec in terms.entitlements:
            cached = await self._cached(customer_id, spec.feature, today)
            if cached is None:
                resolved = await self._resolve(sub, spec.feature, today, metrics)
                cached = await self._store(customer_id, today, resolved)
            results.append(cached)
        return EntitlementsOut(customer_id=customer_external_id, entitlements=results)

    async def _customer_id(self, external_id: str) -> UUID:
        customer = await self._customers.get_by_external_id(external_id)
        if customer is None:
            raise NotFoundError(f"customer {external_id!r} does not exist")
        return customer.id

    async def _cached(self, customer_id: UUID, feature: str, today: date) -> EntitlementOut | None:
        raw = await self._cache.get(customer_id, f"{today.isoformat()}:{feature}")
        if raw is None:
            return None
        return EntitlementOut.model_validate_json(raw).model_copy(update={"cached": True})

    async def _store(
        self, customer_id: UUID, today: date, result: EntitlementOut
    ) -> EntitlementOut:
        await self._cache.set(
            customer_id,
            f"{today.isoformat()}:{result.feature}",
            result.model_dump_json(),
            self._settings.entitlement_cache_ttl_seconds,
        )
        return result

    async def _resolve(
        self,
        sub: Subscription | None,
        feature: str,
        today: date,
        metrics: Mapping[str, Metric] | None = None,
    ) -> EntitlementOut:
        if sub is None:
            return _denied(feature, "no_active_subscription")
        phase = current_phase(sub, today)
        terms = terms_of(phase.plan_version)
        spec = next((e for e in terms.entitlements if e.feature == feature), None)
        if spec is None:
            return _denied(feature, "not_in_plan", plan_code=phase.plan_version.plan.code)

        period = period_containing(sub.billing_anchor, Interval(sub.interval), today)
        base = _base(spec, period.start, period.end, phase.plan_version.plan.code)
        if spec.metric_code is None or spec.limit is None:
            return base.model_copy(update={"allowed": True, "reason": "included"})

        metric = (
            metrics.get(spec.metric_code)
            if metrics is not None
            else await self._metrics.get_by_code(spec.metric_code)
        )
        if metric is None:
            return base.model_copy(update={"allowed": False, "reason": "metric_missing"})
        usage = await self._usage.usage(metric, sub.customer_id, period.starts_at, period.ends_at)
        remaining = max(spec.limit - usage.total, Decimal(0))
        return base.model_copy(
            update={
                "allowed": usage.total < spec.limit,
                "reason": "within_quota" if usage.total < spec.limit else "quota_exhausted",
                "used": usage.total,
                "remaining": remaining,
            }
        )


def _base(spec: FeatureEntitlement, start: date, end: date, plan_code: str) -> EntitlementOut:
    return EntitlementOut(
        feature=spec.feature,
        name=spec.name,
        allowed=False,
        reason="",
        metric_code=spec.metric_code,
        limit=spec.limit,
        used=None,
        remaining=None,
        period_start=start,
        period_end=end,
        plan_code=plan_code,
    )


def _denied(feature: str, reason: str, plan_code: str | None = None) -> EntitlementOut:
    return EntitlementOut(
        feature=feature,
        name=feature,
        allowed=False,
        reason=reason,
        metric_code=None,
        limit=None,
        used=None,
        remaining=None,
        period_start=None,
        period_end=None,
        plan_code=plan_code,
    )
