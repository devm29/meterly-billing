from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from meterly.billing.mappers import current_phase, subscription_out, terms_of
from meterly.billing.repository import CustomerRepository, SubscriptionRepository
from meterly.billing.schemas import SubscriptionOut
from meterly.billing.statuses import SubscriptionStatus
from meterly.db.models import Customer, Subscription
from meterly.errors import ConflictError, NotFoundError
from meterly.money import Currency, Money


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    email: EmailStr | None = None
    currency: Currency = Currency.USD


class CustomerOut(BaseModel):
    id: UUID
    external_id: str
    name: str
    email: str | None
    currency: Currency
    created_at: datetime
    plan_name: str | None
    status: SubscriptionStatus | Literal["none"]
    fixed_monthly: Money | None
    subscription: SubscriptionOut | None


class CustomerPage(BaseModel):
    items: list[CustomerOut]
    total: int
    limit: int
    offset: int


def utc_now() -> datetime:
    return datetime.now(UTC)


class CustomerService:
    def __init__(self, session: AsyncSession, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock
        self._customers = CustomerRepository(session)
        self._subs = SubscriptionRepository(session)

    async def create(self, payload: CustomerCreate) -> CustomerOut:
        customer = Customer(
            external_id=payload.external_id,
            name=payload.name,
            email=str(payload.email) if payload.email else None,
            currency=payload.currency.value,
        )
        self._session.add(customer)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError(f"customer {payload.external_id!r} already exists") from exc
        return await self.get(payload.external_id)

    async def get(self, external_id: str) -> CustomerOut:
        customer = await self._customers.get_by_external_id(external_id)
        if customer is None:
            raise NotFoundError(f"customer {external_id!r} does not exist")
        subs = await self._subs.for_customers([customer.id])
        return self._out(customer, subs.get(customer.id))

    async def require(self, external_id: str) -> Customer:
        customer = await self._customers.get_by_external_id(external_id)
        if customer is None:
            raise NotFoundError(f"customer {external_id!r} does not exist")
        return customer

    async def search(self, query: str | None, limit: int, offset: int) -> CustomerPage:
        rows, total = await self._customers.search(query, limit, offset)
        subs = await self._subs.for_customers([c.id for c in rows])
        return CustomerPage(
            items=[self._out(c, subs.get(c.id)) for c in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def _out(self, customer: Customer, subscription: Subscription | None) -> CustomerOut:
        today = self._clock().astimezone(UTC).date()
        plan_name: str | None = None
        fixed: Money | None = None
        status: SubscriptionStatus | Literal["none"] = "none"
        out: SubscriptionOut | None = None
        if subscription is not None:
            out = subscription_out(subscription, today)
            status = out.status
            phase = current_phase(subscription, today)
            plan_name = phase.plan_version.plan.name
            terms = terms_of(phase.plan_version)
            fixed = Money.of(terms.fixed_amount() / terms.interval.months, terms.currency)
        return CustomerOut(
            id=customer.id,
            external_id=customer.external_id,
            name=customer.name,
            email=customer.email,
            currency=Currency(customer.currency),
            created_at=customer.created_at,
            plan_name=plan_name,
            status=status,
            fixed_monthly=fixed,
            subscription=out,
        )
