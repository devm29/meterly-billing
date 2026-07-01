"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-04 14:42:31.316443
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PARTITION_FUNCTION = """
CREATE OR REPLACE FUNCTION meterly_ensure_event_partitions(first_month date, months integer)
RETURNS integer LANGUAGE plpgsql SET timezone = 'UTC' AS $$
DECLARE
    month_start date;
    partition_name text;
    created integer := 0;
BEGIN
    FOR i IN 0 .. months - 1 LOOP
        month_start := (date_trunc('month', first_month) + make_interval(months => i))::date;
        partition_name := format('usage_events_y%sm%s',
            to_char(month_start, 'YYYY'), to_char(month_start, 'MM'));
        IF to_regclass(partition_name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF usage_events FOR VALUES FROM (%L) TO (%L)',
                partition_name,
                month_start::timestamp AT TIME ZONE 'UTC',
                (month_start + interval '1 month')::timestamp AT TIME ZONE 'UTC');
            created := created + 1;
        END IF;
    END LOOP;
    RETURN created;
END $$;
"""

IMMUTABILITY_TRIGGERS = (
    """
CREATE FUNCTION meterly_guard_finalized_invoice() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'finalized' AND NOT (NEW.status = 'void' AND
        (NEW.subtotal, NEW.total, NEW.number, NEW.usage_snapshot)
            IS NOT DISTINCT FROM (OLD.subtotal, OLD.total, OLD.number, OLD.usage_snapshot)) THEN
        RAISE EXCEPTION 'invoice % is finalized and immutable', OLD.number
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'void' THEN
        RAISE EXCEPTION 'invoice % is void', OLD.id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$
""",
    """
CREATE TRIGGER invoices_immutable BEFORE UPDATE ON invoices
    FOR EACH ROW EXECUTE FUNCTION meterly_guard_finalized_invoice()
""",
    """
CREATE FUNCTION meterly_guard_invoice_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'draft' THEN
        RAISE EXCEPTION 'invoice % is % and cannot be deleted', OLD.id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN OLD;
END $$
""",
    """
CREATE TRIGGER invoices_undeletable BEFORE DELETE ON invoices
    FOR EACH ROW EXECUTE FUNCTION meterly_guard_invoice_delete()
""",
    """
CREATE FUNCTION meterly_guard_finalized_lines() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_status text;
BEGIN
    SELECT status INTO parent_status FROM invoices
        WHERE id = COALESCE(NEW.invoice_id, OLD.invoice_id);
    -- A missing parent on DELETE means a draft is being removed by ON DELETE CASCADE;
    -- non-draft invoices are already blocked by invoices_undeletable.
    IF TG_OP = 'DELETE' AND NOT FOUND THEN
        RETURN OLD;
    END IF;
    IF parent_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'lines of a % invoice cannot change', parent_status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END $$
""",
    """
CREATE TRIGGER invoice_lines_immutable BEFORE INSERT OR UPDATE OR DELETE ON invoice_lines
    FOR EACH ROW EXECUTE FUNCTION meterly_guard_finalized_lines()
""",
)

NO_OVERLAP_CONSTRAINTS = (
    """
ALTER TABLE subscriptions ADD CONSTRAINT ex_subscriptions_no_overlap
    EXCLUDE USING gist (customer_id WITH =, daterange(started_on, ends_on) WITH &&)
""",
    """
ALTER TABLE subscription_phases ADD CONSTRAINT ex_subscription_phases_no_overlap
    EXCLUDE USING gist (subscription_id WITH =, daterange(starts_on, ends_on) WITH &&)
    DEFERRABLE INITIALLY DEFERRED
""",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "billable_metrics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_code", sa.String(length=64), nullable=False),
        sa.Column("aggregation", sa.String(length=16), nullable=False),
        sa.Column("field_path", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "group_by",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("unit", sa.String(length=32), server_default="units", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregation = 'count' OR field_path IS NOT NULL",
            name=op.f("ck_billable_metrics_field_required"),
        ),
        sa.CheckConstraint(
            "aggregation IN ('count','sum','max','unique_count','latest')",
            name=op.f("ck_billable_metrics_aggregation"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billable_metrics")),
        sa.UniqueConstraint("code", name=op.f("uq_billable_metrics_code")),
    )
    op.create_index(
        op.f("ix_billable_metrics_event_code"), "billable_metrics", ["event_code"], unique=False
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("external_id", name=op.f("uq_customers_external_id")),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", name=op.f("uq_plans_code")),
    )
    op.create_table(
        "usage_event_keys",
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("customer_id", "transaction_id", name=op.f("pk_usage_event_keys")),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("event_code", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "timestamp", name=op.f("pk_usage_events")),
        postgresql_partition_by="RANGE (timestamp)",
    )
    op.create_index(
        "ix_usage_events_customer_code_ts",
        "usage_events",
        ["customer_id", "event_code", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_recent",
        "usage_events",
        [sa.text("timestamp DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_table(
        "plan_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
            name=op.f("fk_plan_versions_plan_id_plans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_versions")),
        sa.UniqueConstraint("plan_id", "version", name=op.f("uq_plan_versions_plan_id")),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("billing_anchor", sa.Date(), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("trial_ends_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("billed_through", sa.Date(), nullable=False),
        sa.Column("current_period_end", sa.Date(), nullable=False),
        sa.Column("close_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_close_error", sa.Text(), nullable=True),
        sa.Column("next_close_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_subscriptions_customer_id_customers")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(
        op.f("ix_subscriptions_customer_id"), "subscriptions", ["customer_id"], unique=False
    )
    op.create_index(
        "ix_subscriptions_due",
        "subscriptions",
        ["current_period_end"],
        unique=False,
        postgresql_where=sa.text("billed_through < COALESCE(ends_on, 'infinity'::date)"),
    )
    op.create_index(
        "uq_subscriptions_one_live_per_customer",
        "subscriptions",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("ends_on IS NULL"),
    )
    op.create_table(
        "usage_rollups_hourly",
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.UUID(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("event_count", sa.BigInteger(), nullable=False),
        sa.Column("sum_value", sa.Numeric(), nullable=False),
        sa.Column("max_value", sa.Numeric(), nullable=True),
        sa.Column("latest_value", sa.Numeric(), nullable=True),
        sa.Column("latest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["billable_metrics.id"],
            name=op.f("fk_usage_rollups_hourly_metric_id_billable_metrics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "customer_id",
            "metric_id",
            "bucket_start",
            "group_key",
            name=op.f("pk_usage_rollups_hourly"),
        ),
    )
    op.create_index(
        "ix_usage_rollups_metric_bucket",
        "usage_rollups_hourly",
        ["metric_id", "bucket_start"],
        unique=False,
    )
    op.create_table(
        "usage_unique_values",
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.UUID(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["billable_metrics.id"],
            name=op.f("fk_usage_unique_values_metric_id_billable_metrics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "customer_id",
            "metric_id",
            "bucket_start",
            "group_key",
            "value",
            name=op.f("pk_usage_unique_values"),
        ),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("total", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("usage_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "price_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'finalized') = (number IS NOT NULL AND finalized_at IS NOT NULL) OR status = 'void'",
            name=op.f("ck_invoices_finalized_has_number"),
        ),
        sa.CheckConstraint(
            "status IN ('draft','finalized','void')", name=op.f("ck_invoices_status")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_invoices_customer_id_customers")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_invoices_subscription_id_subscriptions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("number", name=op.f("uq_invoices_number")),
        sa.UniqueConstraint(
            "subscription_id", "period_start", name=op.f("uq_invoices_subscription_id")
        ),
    )
    op.create_index(op.f("ix_invoices_customer_id"), "invoices", ["customer_id"], unique=False)
    op.create_index("ix_invoices_period_start", "invoices", ["period_start"], unique=False)
    op.create_index(
        "ix_invoices_status_created", "invoices", ["status", "created_at"], unique=False
    )
    op.create_table(
        "subscription_phases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("plan_version_id", sa.UUID(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "ends_on IS NULL OR ends_on > starts_on", name=op.f("ck_subscription_phases_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id"],
            ["plan_versions.id"],
            name=op.f("fk_subscription_phases_plan_version_id_plan_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_subscription_phases_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription_phases")),
    )
    op.create_index(
        op.f("ix_subscription_phases_subscription_id"),
        "subscription_phases",
        ["subscription_id"],
        unique=False,
    )
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("line_key", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("charge_key", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=True),
        sa.Column("plan_version_id", sa.UUID(), nullable=False),
        sa.Column("phase_start", sa.Date(), nullable=False),
        sa.Column("phase_end", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("billable_quantity", sa.Numeric(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_invoice_lines_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id"],
            ["plan_versions.id"],
            name=op.f("fk_invoice_lines_plan_version_id_plan_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_lines")),
        sa.UniqueConstraint("invoice_id", "line_key", name=op.f("uq_invoice_lines_invoice_id")),
    )
    op.create_index(
        op.f("ix_invoice_lines_invoice_id"), "invoice_lines", ["invoice_id"], unique=False
    )
    op.create_table(
        "invoice_documents",
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "rendered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_invoice_documents_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("invoice_id", name=op.f("pk_invoice_documents")),
    )

    op.execute(PARTITION_FUNCTION)
    op.execute("CREATE TABLE usage_events_default PARTITION OF usage_events DEFAULT")
    op.execute(
        "SELECT meterly_ensure_event_partitions(date_trunc('month', now() - interval '24 months')::date, 28)"
    )
    op.execute("CREATE SEQUENCE invoice_number_seq START 1001")
    for statement in (*IMMUTABILITY_TRIGGERS, *NO_OVERLAP_CONSTRAINTS):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("invoice_documents")
    op.execute("DROP FUNCTION IF EXISTS meterly_guard_finalized_lines() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS meterly_guard_invoice_delete() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS meterly_guard_finalized_invoice() CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS invoice_number_seq")
    op.drop_index(op.f("ix_invoice_lines_invoice_id"), table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index(op.f("ix_subscription_phases_subscription_id"), table_name="subscription_phases")
    op.drop_table("subscription_phases")
    op.drop_index("ix_invoices_status_created", table_name="invoices")
    op.drop_index("ix_invoices_period_start", table_name="invoices")
    op.drop_index(op.f("ix_invoices_customer_id"), table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("usage_unique_values")
    op.drop_index("ix_usage_rollups_metric_bucket", table_name="usage_rollups_hourly")
    op.drop_table("usage_rollups_hourly")
    op.drop_index(
        "uq_subscriptions_one_live_per_customer",
        table_name="subscriptions",
        postgresql_where=sa.text("ends_on IS NULL"),
    )
    op.drop_index(
        "ix_subscriptions_due",
        table_name="subscriptions",
        postgresql_where=sa.text("billed_through < COALESCE(ends_on, 'infinity'::date)"),
    )
    op.drop_index(op.f("ix_subscriptions_customer_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("plan_versions")
    op.drop_index("ix_usage_events_recent", table_name="usage_events")
    op.drop_index("ix_usage_events_customer_code_ts", table_name="usage_events")
    op.drop_table("usage_events")
    op.execute("DROP FUNCTION IF EXISTS meterly_ensure_event_partitions(date, integer)")
    op.drop_table("usage_event_keys")
    op.drop_table("plans")
    op.drop_table("customers")
    op.drop_index(op.f("ix_billable_metrics_event_code"), table_name="billable_metrics")
    op.drop_table("billable_metrics")
