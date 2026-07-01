from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from meterly.db.base import Base, Timestamped

MONEY = Numeric(20, 4)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Customer(Timestamped, Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    external_id: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    currency: Mapped[str] = mapped_column(String(3))

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="customer")


class BillableMetric(Timestamped, Base):
    __tablename__ = "billable_metrics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    event_code: Mapped[str] = mapped_column(String(64), index=True)
    aggregation: Mapped[str] = mapped_column(String(16))
    field_path: Mapped[list[Any] | None] = mapped_column(JSONB)
    group_by: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    unit: Mapped[str] = mapped_column(String(32), server_default="units")

    __table_args__ = (
        CheckConstraint(
            "aggregation IN ('count','sum','max','unique_count','latest')", name="aggregation"
        ),
        CheckConstraint("aggregation = 'count' OR field_path IS NOT NULL", name="field_required"),
    )


class Plan(Timestamped, Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)

    versions: Mapped[list[PlanVersion]] = relationship(
        back_populates="plan", order_by="PlanVersion.version"
    )


class PlanVersion(Timestamped, Base):
    __tablename__ = "plan_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    terms: Mapped[dict[str, Any]] = mapped_column(JSONB)

    plan: Mapped[Plan] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("plan_id", "version"),)


class Subscription(Timestamped, Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    billing_anchor: Mapped[date] = mapped_column(Date)
    interval: Mapped[str] = mapped_column(String(8))
    started_on: Mapped[date] = mapped_column(Date)
    trial_ends_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    billed_through: Mapped[date] = mapped_column(Date)
    current_period_end: Mapped[date] = mapped_column(Date)
    close_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    last_close_error: Mapped[str | None] = mapped_column(Text)
    next_close_attempt_at: Mapped[datetime | None]

    customer: Mapped[Customer] = relationship(back_populates="subscriptions")
    phases: Mapped[list[SubscriptionPhase]] = relationship(
        back_populates="subscription", order_by="SubscriptionPhase.starts_on"
    )

    __table_args__ = (
        Index(
            "ix_subscriptions_due",
            "current_period_end",
            postgresql_where=text("billed_through < COALESCE(ends_on, 'infinity'::date)"),
        ),
        Index(
            "uq_subscriptions_one_live_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("ends_on IS NULL"),
        ),
        ExcludeConstraint(
            ("customer_id", "="),
            (text("daterange(started_on, ends_on)"), "&&"),
            using="gist",
            name="ex_subscriptions_no_overlap",
        ),
    )


class SubscriptionPhase(Base):
    __tablename__ = "subscription_phases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    plan_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_versions.id"))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)

    subscription: Mapped[Subscription] = relationship(back_populates="phases")
    plan_version: Mapped[PlanVersion] = relationship()

    __table_args__ = (
        CheckConstraint("ends_on IS NULL OR ends_on > starts_on", name="ordered"),
        ExcludeConstraint(
            ("subscription_id", "="),
            (text("daterange(starts_on, ends_on)"), "&&"),
            using="gist",
            name="ex_subscription_phases_no_overlap",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


class UsageEvent(Base):
    """Raw, append-only event log, range-partitioned by month on ``timestamp``."""

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    transaction_id: Mapped[str] = mapped_column(String(128))
    event_code: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime]
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("id", "timestamp"),
        Index("ix_usage_events_customer_code_ts", "customer_id", "event_code", "timestamp"),
        Index("ix_usage_events_recent", text("timestamp DESC"), text("id DESC")),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )


class UsageEventKey(Base):
    """Idempotency ledger. Partitioned tables cannot enforce uniqueness without the
    partition key, so (customer, transaction_id) uniqueness lives here."""

    __tablename__ = "usage_event_keys"

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_timestamp: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UsageRollupHourly(Base):
    __tablename__ = "usage_rollups_hourly"

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    metric_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billable_metrics.id", ondelete="CASCADE")
    )
    bucket_start: Mapped[datetime]
    group_key: Mapped[str] = mapped_column(Text)
    event_count: Mapped[int] = mapped_column(BigInteger)
    sum_value: Mapped[Decimal]
    max_value: Mapped[Decimal | None]
    latest_value: Mapped[Decimal | None]
    latest_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("customer_id", "metric_id", "bucket_start", "group_key"),
        Index("ix_usage_rollups_metric_bucket", "metric_id", "bucket_start"),
    )


class UsageUniqueValue(Base):
    """Distinct values per hour bucket, so UNIQUE_COUNT can be answered without raw scans."""

    __tablename__ = "usage_unique_values"

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    metric_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billable_metrics.id", ondelete="CASCADE")
    )
    bucket_start: Mapped[datetime]
    group_key: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        PrimaryKeyConstraint("customer_id", "metric_id", "bucket_start", "group_key", "value"),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = _uuid_pk()
    number: Mapped[str | None] = mapped_column(String(32), unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"))
    status: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    total: Mapped[Decimal] = mapped_column(MONEY)
    usage_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    price_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finalized_at: Mapped[datetime | None]

    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice", order_by="InvoiceLine.position", cascade="all, delete-orphan"
    )
    customer: Mapped[Customer] = relationship()

    __table_args__ = (
        UniqueConstraint("subscription_id", "period_start"),
        CheckConstraint("status IN ('draft','finalized','void')", name="status"),
        CheckConstraint(
            "(status = 'finalized') = (number IS NOT NULL AND finalized_at IS NOT NULL)"
            " OR status = 'void'",
            name="finalized_has_number",
        ),
        Index("ix_invoices_status_created", "status", "created_at"),
        Index("ix_invoices_period_start", "period_start"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    line_key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16))
    charge_key: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    metric_code: Mapped[str | None] = mapped_column(String(64))
    plan_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plan_versions.id"))
    phase_start: Mapped[date] = mapped_column(Date)
    phase_end: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal]
    billable_quantity: Mapped[Decimal]
    amount: Mapped[Decimal] = mapped_column(MONEY)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")

    __table_args__ = (UniqueConstraint("invoice_id", "line_key"),)


class InvoiceDocument(Base):
    """Rendered PDF, kept apart from ``invoices`` so the immutability trigger never sees it."""

    __tablename__ = "invoice_documents"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), primary_key=True
    )
    content_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    rendered_at: Mapped[datetime] = mapped_column(server_default=func.now())
