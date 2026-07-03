from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, or_, select, text, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from meterly.billing.statuses import InvoiceStatus
from meterly.db.models import (
    Customer,
    Invoice,
    InvoiceDocument,
    Plan,
    PlanVersion,
    Subscription,
    SubscriptionPhase,
)


def live_on(day: date) -> list[ColumnElement[bool]]:
    return [Subscription.started_on <= day, func.coalesce(Subscription.ends_on, date.max) > day]


class PlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self) -> list[Plan]:
        stmt = (
            select(Plan).options(selectinload(Plan.versions)).order_by(Plan.created_at, Plan.code)
        )
        return list(await self._session.scalars(stmt))

    async def get_by_code(self, code: str) -> Plan | None:
        stmt = select(Plan).options(selectinload(Plan.versions)).where(Plan.code == code)
        return await self._session.scalar(stmt)

    async def get_version(self, version_id: UUID) -> PlanVersion | None:
        stmt = (
            select(PlanVersion)
            .options(selectinload(PlanVersion.plan))
            .where(PlanVersion.id == version_id)
        )
        return await self._session.scalar(stmt)

    async def versions(self, ids: Sequence[UUID]) -> dict[UUID, PlanVersion]:
        if not ids:
            return {}
        stmt = (
            select(PlanVersion)
            .options(selectinload(PlanVersion.plan))
            .where(PlanVersion.id.in_(set(ids)))
        )
        return {v.id: v for v in await self._session.scalars(stmt)}


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_external_id(self, external_id: str) -> Customer | None:
        return await self._session.scalar(
            select(Customer).where(Customer.external_id == external_id)
        )

    async def search(
        self, query: str | None, limit: int, offset: int
    ) -> tuple[list[Customer], int]:
        stmt = select(Customer)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(Customer.name.ilike(pattern) | Customer.external_id.ilike(pattern))
        total = await self._session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = await self._session.scalars(stmt.order_by(Customer.name).limit(limit).offset(offset))
        return list(rows), int(total or 0)

    async def lock(self, customer_id: UUID) -> None:
        """Exclusive row lock; ingestion holds a shared one while it checks closed periods."""
        await self._session.execute(
            select(Customer.id).where(Customer.id == customer_id).with_for_update()
        )


def _subscription_query() -> Select[Subscription]:
    return select(Subscription).options(
        selectinload(Subscription.customer),
        selectinload(Subscription.phases)
        .selectinload(SubscriptionPhase.plan_version)
        .selectinload(PlanVersion.plan),
    )


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, subscription_id: UUID, *, lock: bool = False) -> Subscription | None:
        stmt = _subscription_query().where(Subscription.id == subscription_id)
        if lock:
            stmt = stmt.with_for_update(of=Subscription)
        return await self._session.scalar(stmt)

    async def live_for_customer(self, customer_id: UUID, day: date) -> Subscription | None:
        stmt = (
            _subscription_query()
            .where(Subscription.customer_id == customer_id, *live_on(day))
            .order_by(Subscription.started_on.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def latest_for_customer(self, customer_id: UUID) -> Subscription | None:
        stmt = (
            _subscription_query()
            .where(Subscription.customer_id == customer_id)
            .order_by(Subscription.started_on.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def for_customers(self, customer_ids: Sequence[UUID]) -> dict[UUID, Subscription]:
        if not customer_ids:
            return {}
        stmt = (
            _subscription_query()
            .where(Subscription.customer_id.in_(customer_ids))
            .order_by(Subscription.customer_id, Subscription.started_on.desc())
        )
        result: dict[UUID, Subscription] = {}
        for sub in await self._session.scalars(stmt):
            result.setdefault(sub.customer_id, sub)
        return result

    async def overlapping(self, customer_id: UUID, start: date) -> Subscription | None:
        """A subscription of the customer that is still running on or after ``start``."""
        stmt = (
            select(Subscription)
            .where(
                Subscription.customer_id == customer_id,
                func.coalesce(Subscription.ends_on, date.max) > start,
            )
            .order_by(Subscription.started_on)
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def claim_due(self, closable_through: date, now: datetime, limit: int) -> list[UUID]:
        """Lock subscriptions whose period can be closed; concurrent workers skip each other.

        Rows that failed recently are skipped until their back-off expires, so one broken
        subscription cannot starve the rest of the queue.
        """
        stmt = (
            select(Subscription.id)
            .where(
                Subscription.current_period_end <= closable_through,
                Subscription.billed_through < func.coalesce(Subscription.ends_on, date.max),
                or_(
                    Subscription.next_close_attempt_at.is_(None),
                    Subscription.next_close_attempt_at <= now,
                ),
            )
            .order_by(Subscription.current_period_end, Subscription.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(await self._session.scalars(stmt))

    async def live(self, day: date) -> list[Subscription]:
        return list(await self._session.scalars(_subscription_query().where(*live_on(day))))


class InvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, invoice_id: UUID, *, lock: bool = False) -> Invoice | None:
        stmt = (
            select(Invoice)
            .options(selectinload(Invoice.lines), selectinload(Invoice.customer))
            .where(Invoice.id == invoice_id)
        )
        if lock:
            stmt = stmt.with_for_update(of=Invoice)
        return await self._session.scalar(stmt)

    async def page(
        self,
        *,
        status: InvoiceStatus | None,
        customer_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Invoice], int]:
        stmt = select(Invoice).options(selectinload(Invoice.customer))
        if status:
            stmt = stmt.where(Invoice.status == status)
        if customer_id:
            stmt = stmt.where(Invoice.customer_id == customer_id)
        total = await self._session.scalar(
            select(func.count()).select_from(stmt.with_only_columns(Invoice.id).subquery())
        )
        rows = await self._session.scalars(
            stmt.order_by(Invoice.period_start.desc(), Invoice.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def recent_for_subscription(self, subscription_id: UUID, limit: int) -> list[Invoice]:
        stmt = (
            select(Invoice)
            .where(
                Invoice.subscription_id == subscription_id,
                Invoice.status != InvoiceStatus.VOID,
            )
            .order_by(Invoice.period_start.desc())
            .limit(limit)
        )
        return list(await self._session.scalars(stmt))

    async def claim_due_drafts(
        self, created_before: datetime, limit: int, exclude: Sequence[UUID] = ()
    ) -> list[UUID]:
        stmt = (
            select(Invoice.id)
            .where(Invoice.status == InvoiceStatus.DRAFT, Invoice.created_at <= created_before)
            .where(Invoice.id.not_in(exclude) if exclude else true())
            .order_by(Invoice.created_at, Invoice.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(await self._session.scalars(stmt))

    async def stored_pdf(self, invoice_id: UUID) -> bytes | None:
        return await self._session.scalar(
            select(InvoiceDocument.content).where(InvoiceDocument.invoice_id == invoice_id)
        )

    async def store_pdf(self, invoice_id: UUID, content: bytes) -> None:
        stmt = pg_insert(InvoiceDocument).values(
            invoice_id=invoice_id, content_type="application/pdf", content=content
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["invoice_id"],
                set_={"content": stmt.excluded.content, "rendered_at": func.now()},
            )
        )

    async def finalized_without_document(self, limit: int) -> list[UUID]:
        stmt = (
            select(Invoice.id)
            .outerjoin(InvoiceDocument, InvoiceDocument.invoice_id == Invoice.id)
            .where(Invoice.status == InvoiceStatus.FINALIZED, InvoiceDocument.invoice_id.is_(None))
            .order_by(Invoice.finalized_at)
            .limit(limit)
        )
        return list(await self._session.scalars(stmt))

    async def next_number(self) -> int:
        value = await self._session.scalar(text("SELECT nextval('invoice_number_seq')"))
        return int(value)
