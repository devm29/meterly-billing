from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.mappers import current_phase, subscription_status, terms_of
from meterly.billing.periods import add_months
from meterly.billing.repository import SubscriptionRepository
from meterly.billing.statuses import InvoiceStatus, SubscriptionStatus
from meterly.db.models import Customer, Invoice, InvoiceLine
from meterly.money import Currency, Money


class RevenueMonth(BaseModel):
    month: date
    fixed: Money
    usage: Money
    total: Money
    invoices: int


class TopCustomer(BaseModel):
    customer_id: str
    name: str
    revenue: Money


class Overview(BaseModel):
    """``mrr`` is billed MRR: finalized invoices of the last complete calendar month.

    Drafts can still be re-rated, so they are reported separately as ``draft_total``.
    """

    currency: Currency
    mrr: Money
    mrr_previous: Money
    contracted_mrr: Money
    usage_share: Decimal
    active_customers: int
    trialing_customers: int
    arpa: Money
    draft_invoices: int
    draft_total: Money
    revenue: list[RevenueMonth]
    top_customers: list[TopCustomer]


def utc_now() -> datetime:
    return datetime.now(UTC)


class AnalyticsService:
    def __init__(self, session: AsyncSession, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock
        self._subs = SubscriptionRepository(session)

    async def revenue(self, currency: Currency, months: int) -> list[RevenueMonth]:
        today = self._clock().astimezone(UTC).date()
        first = add_months(today.replace(day=1), -(months - 1))
        # Revenue is attributed to the month an invoice is issued, i.e. when its period ends.
        month = cast(func.date_trunc("month", Invoice.period_end), Date).label("month")
        stmt = (
            select(
                month,
                func.coalesce(func.sum(case((InvoiceLine.kind == "fixed", InvoiceLine.amount))), 0),
                func.coalesce(func.sum(case((InvoiceLine.kind != "fixed", InvoiceLine.amount))), 0),
                func.count(func.distinct(Invoice.id)),
            )
            .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
            .where(
                Invoice.currency == currency.value,
                Invoice.status == InvoiceStatus.FINALIZED,
                Invoice.period_end >= first,
            )
            .group_by(month)
        )
        found = {row[0]: row for row in (await self._session.execute(stmt)).all()}
        result: list[RevenueMonth] = []
        for i in range(months):
            m = add_months(first, i)
            row = found.get(m)
            fixed = Money.of(row[1] if row else 0, currency)
            usage = Money.of(row[2] if row else 0, currency)
            result.append(
                RevenueMonth(
                    month=m,
                    fixed=fixed,
                    usage=usage,
                    total=fixed + usage,
                    invoices=int(row[3]) if row else 0,
                )
            )
        return result

    async def overview(self, currency: Currency) -> Overview:
        today = self._clock().astimezone(UTC).date()
        revenue = await self.revenue(currency, 12)
        closed = [r for r in revenue if r.month < today.replace(day=1)]
        zero = Money.zero(currency)
        mrr = closed[-1].total if closed else zero
        previous = closed[-2].total if len(closed) > 1 else zero
        usage_last = closed[-1].usage if closed else zero

        contracted = zero
        active = trialing = 0
        for sub in await self._subs.live(today):
            if sub.customer.currency != currency.value:
                continue
            status = subscription_status(sub, today)
            if status is SubscriptionStatus.TRIALING:
                trialing += 1
                continue
            active += 1
            terms = terms_of(current_phase(sub, today).plan_version)
            contracted += Money.of(terms.fixed_amount() / terms.interval.months, currency)

        drafts = (
            await self._session.execute(
                select(func.count(), func.coalesce(func.sum(Invoice.total), 0)).where(
                    Invoice.status == InvoiceStatus.DRAFT, Invoice.currency == currency.value
                )
            )
        ).one()
        return Overview(
            currency=currency,
            mrr=mrr,
            mrr_previous=previous,
            contracted_mrr=contracted,
            usage_share=(usage_last.amount / mrr.amount).quantize(Decimal("0.0001"))
            if mrr.amount
            else Decimal(0),
            active_customers=active,
            trialing_customers=trialing,
            arpa=Money.of(mrr.amount / active, currency) if active else zero,
            draft_invoices=int(drafts[0]),
            draft_total=Money.of(drafts[1], currency),
            revenue=revenue,
            top_customers=await self._top_customers(currency, today),
        )

    async def _top_customers(self, currency: Currency, today: date) -> list[TopCustomer]:
        since = add_months(today.replace(day=1), -3)
        revenue = func.sum(Invoice.total).label("revenue")
        stmt = (
            select(Customer.external_id, Customer.name, revenue)
            .join(Invoice, Invoice.customer_id == Customer.id)
            .where(
                Invoice.currency == currency.value,
                Invoice.status == InvoiceStatus.FINALIZED,
                Invoice.period_start >= since,
            )
            .group_by(Customer.id)
            .order_by(revenue.desc())
            .limit(5)
        )
        return [
            TopCustomer(customer_id=ext, name=name, revenue=Money.of(total, currency))
            for ext, name, total in (await self._session.execute(stmt)).all()
        ]
