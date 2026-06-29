"""Seed a realistic AI-platform tenant: six months of usage, plan changes, invoices.

The timeline is replayed day by day through the real services, so every invoice was
produced by the same period-close code path the worker runs.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from meterly.api.app import build_container
from meterly.billing.customers import CustomerCreate, CustomerService
from meterly.billing.invoicing import run_close_cycle
from meterly.billing.plans import PlanService
from meterly.billing.schemas import Cancellation, PlanChange, PlanCreate, SubscriptionCreate
from meterly.billing.subscriptions import SubscriptionService
from meterly.billing.terms import PlanTerms
from meterly.config import get_settings
from meterly.entitlements.cache import InMemoryEntitlementCache
from meterly.ingestion.service import IngestionService
from meterly.log import configure_logging
from meterly.metering.definitions import MetricDefinition
from meterly.metering.service import MeteringService

METRICS: list[dict[str, Any]] = [
    {
        "code": "llm_tokens",
        "name": "LLM tokens",
        "description": "Prompt plus completion tokens across all models",
        "event_code": "llm.completion",
        "aggregation": "sum",
        "field": "usage.total_tokens",
        "group_by": ["model"],
        "unit": "tokens",
    },
    {
        "code": "api_requests",
        "name": "API requests",
        "event_code": "llm.completion",
        "aggregation": "count",
        "unit": "requests",
    },
    {
        "code": "monthly_active_users",
        "name": "Monthly active users",
        "event_code": "llm.completion",
        "aggregation": "unique_count",
        "field": "end_user_id",
        "unit": "users",
    },
    {
        "code": "seats",
        "name": "Seats",
        "event_code": "seat.sync",
        "aggregation": "latest",
        "field": "seats",
        "unit": "seats",
    },
    {
        "code": "storage_gb",
        "name": "Vector storage",
        "event_code": "storage.snapshot",
        "aggregation": "max",
        "field": "gb",
        "unit": "GB",
    },
]


def _tokens(tiers: list[tuple[int | None, str]], free: int) -> dict[str, Any]:
    return {
        "model": "graduated",
        "free_units": str(free),
        "tiers": [
            {"up_to": None if up is None else str(up), "unit_price": price} for up, price in tiers
        ],
    }


PLANS: list[dict[str, Any]] = [
    {
        "code": "starter",
        "name": "Starter",
        "description": "For prototypes and side projects",
        "terms": {
            "currency": "USD",
            "trial_days": 14,
            "charges": [
                {
                    "key": "platform",
                    "name": "Platform fee",
                    "price": {"model": "flat", "amount": "29"},
                },
                {
                    "key": "tokens",
                    "name": "LLM tokens",
                    "metric_code": "llm_tokens",
                    "price": _tokens([(None, "0.000012")], 1_000_000),
                },
            ],
            "entitlements": [
                {
                    "feature": "api",
                    "name": "API requests",
                    "metric_code": "api_requests",
                    "limit": "5000",
                },
                {"feature": "seats", "name": "Seats", "metric_code": "seats", "limit": "5"},
            ],
        },
    },
    {
        "code": "growth",
        "name": "Growth",
        "description": "For teams shipping AI features to production",
        "terms": {
            "currency": "USD",
            "minimum_commitment": "400",
            "charges": [
                {
                    "key": "platform",
                    "name": "Platform fee",
                    "price": {"model": "flat", "amount": "249"},
                },
                {
                    "key": "tokens",
                    "name": "LLM tokens",
                    "metric_code": "llm_tokens",
                    "price": _tokens(
                        [(100_000_000, "0.00001"), (1_000_000_000, "0.000008"), (None, "0.000006")],
                        5_000_000,
                    ),
                },
                {
                    "key": "seats",
                    "name": "Seats",
                    "metric_code": "seats",
                    "price": {"model": "per_unit", "unit_price": "12", "free_units": "5"},
                },
                {
                    "key": "storage",
                    "name": "Vector storage",
                    "metric_code": "storage_gb",
                    "price": {
                        "model": "package",
                        "package_size": "10",
                        "package_price": "4.50",
                        "free_units": "20",
                    },
                },
            ],
            "entitlements": [
                {
                    "feature": "api",
                    "name": "API requests",
                    "metric_code": "api_requests",
                    "limit": "250000",
                },
                {"feature": "seats", "name": "Seats", "metric_code": "seats", "limit": "50"},
                {"feature": "sso", "name": "Single sign-on"},
            ],
        },
    },
    {
        "code": "scale",
        "name": "Scale",
        "description": "For high-volume workloads with volume discounts",
        "terms": {
            "currency": "USD",
            "minimum_commitment": "1500",
            "charges": [
                {
                    "key": "platform",
                    "name": "Platform fee",
                    "price": {"model": "flat", "amount": "1200"},
                },
                {
                    "key": "tokens",
                    "name": "LLM tokens",
                    "metric_code": "llm_tokens",
                    "price": {
                        "model": "volume",
                        "tiers": [
                            {"up_to": "250000000", "unit_price": "0.0000085"},
                            {"up_to": "1000000000", "unit_price": "0.000007"},
                            {"up_to": None, "unit_price": "0.0000055"},
                        ],
                    },
                },
                {
                    "key": "seats",
                    "name": "Seats",
                    "metric_code": "seats",
                    "price": {"model": "per_unit", "unit_price": "10", "free_units": "20"},
                },
                {
                    "key": "mau",
                    "name": "Monthly active users",
                    "metric_code": "monthly_active_users",
                    "price": {
                        "model": "graduated",
                        "tiers": [
                            {"up_to": "1000", "unit_price": "0"},
                            {"up_to": "10000", "unit_price": "0.04"},
                            {"up_to": None, "unit_price": "0.02"},
                        ],
                    },
                },
                {
                    "key": "storage",
                    "name": "Vector storage",
                    "metric_code": "storage_gb",
                    "price": {"model": "package", "package_size": "50", "package_price": "15"},
                },
            ],
            "entitlements": [
                {"feature": "api", "name": "API requests", "metric_code": "api_requests"},
                {"feature": "seats", "name": "Seats", "metric_code": "seats", "limit": "500"},
                {"feature": "sso", "name": "Single sign-on"},
                {"feature": "audit_log", "name": "Audit log"},
            ],
        },
    },
]

GROWTH_V2_TOKENS = _tokens(
    [(100_000_000, "0.0000095"), (1_000_000_000, "0.0000075"), (None, "0.0000055")], 5_000_000
)

COMPANIES = [
    ("northwind", "Northwind Labs"),
    ("helios", "Helios Health"),
    ("tandem", "Tandem Legal"),
    ("quillbot", "Quill & Co"),
    ("arcadia", "Arcadia Robotics"),
    ("ferrous", "Ferrous Analytics"),
    ("lumen", "Lumen Learning"),
    ("brightpath", "Brightpath Logistics"),
    ("cobalt", "Cobalt Security"),
    ("juniper", "Juniper Retail"),
    ("oakline", "Oakline Insurance"),
    ("pinecrest", "Pinecrest Bank"),
    ("riverside", "Riverside Media"),
    ("sable", "Sable Studios"),
    ("tessera", "Tessera Maps"),
    ("umbra", "Umbra Games"),
    ("vantage", "Vantage Capital"),
    ("willow", "Willow Care"),
    ("zephyr", "Zephyr Travel"),
    ("mosaic", "Mosaic HR"),
    ("kepler", "Kepler Space"),
    ("drift", "Drift Commerce"),
    ("ember", "Ember Energy"),
    ("granite", "Granite Construction"),
]
MODELS = [("claude-sonnet-4-5", 0.55), ("claude-haiku-4-5", 0.35), ("claude-opus-4-1", 0.10)]


@dataclass
class Tenant:
    external_id: str
    name: str
    plan: str
    start: date
    daily_requests: float
    tokens_per_request: int
    users: int
    seats: int
    storage_gb: float
    growth: float
    trial_days: int | None = None
    upgrade: tuple[date, str] | None = None
    cancel_on: date | None = None
    subscription_id: Any = None
    changes: list[Any] = field(default_factory=list)


def build_tenants(rng: random.Random, today: date) -> list[Tenant]:
    tenants: list[Tenant] = []
    first = today.replace(day=1) - timedelta(days=185)
    for index, (ext, name) in enumerate(COMPANIES):
        plan = "scale" if index % 6 == 0 else "starter" if index % 3 == 1 else "growth"
        start = first + timedelta(days=rng.randint(0, 120))
        size = {"starter": 0.25, "growth": 1.0, "scale": 3.2}[plan] * rng.uniform(0.6, 1.5)
        tenant = Tenant(
            external_id=ext,
            name=name,
            plan=plan,
            start=start,
            daily_requests=40 * size,
            tokens_per_request=rng.choice(
                [40_000, 60_000, 80_000] if plan == "scale" else [6_000, 12_000, 24_000, 36_000]
            ),
            users=int(300 * size * rng.uniform(0.5, 4)),
            seats=max(2, int(8 * size)),
            storage_gb=40 * size,
            growth=rng.uniform(0.002, 0.012),
            trial_days=14 if plan == "starter" else None,
        )
        if plan == "starter" and index % 2 == 0:
            tenant.upgrade = (start + timedelta(days=rng.randint(35, 70)), "growth")
        elif plan == "growth" and index in (5, 11):
            tenant.upgrade = (start + timedelta(days=rng.randint(40, 90)), "scale")
        if index == 22:
            tenant.cancel_on = start + timedelta(days=75)
        tenants.append(tenant)
    return tenants


def day_events(
    rng: random.Random, tenant: Tenant, day: date, until: datetime
) -> list[dict[str, Any]]:
    if day < tenant.start or (tenant.cancel_on and day >= tenant.cancel_on):
        return []
    age = (day - tenant.start).days
    trend = math.exp(tenant.growth * age)
    weekday = 0.55 if day.weekday() >= 5 else 1.0
    requests = max(
        0, int(rng.gauss(tenant.daily_requests * trend * weekday, tenant.daily_requests * 0.15))
    )
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    events: list[dict[str, Any]] = []
    active_users = max(1, int(tenant.users * min(1.0, 0.25 + age / 120)))
    for i in range(requests):
        at = base + timedelta(seconds=rng.randint(0, 86_399))
        if at > until:
            continue
        model = rng.choices([m for m, _ in MODELS], weights=[w for _, w in MODELS])[0]
        tokens = max(200, int(rng.lognormvariate(math.log(tenant.tokens_per_request), 0.5)))
        events.append(
            {
                "transaction_id": f"cmp_{tenant.external_id}_{day:%Y%m%d}_{i:05d}",
                "customer_id": tenant.external_id,
                "code": "llm.completion",
                "timestamp": at.isoformat(),
                "properties": {
                    "model": model,
                    "end_user_id": f"u_{rng.randint(1, active_users)}",
                    "usage": {"input_tokens": int(tokens * 0.8), "total_tokens": tokens},
                    "latency_ms": rng.randint(300, 9000),
                },
            }
        )
    seats = int(tenant.seats * (1 + age / 90))
    for hour, kind in ((9, "seat.sync"), (3, "storage.snapshot"), (15, "storage.snapshot")):
        at = base + timedelta(hours=hour)
        if at > until:
            continue
        props: dict[str, Any] = (
            {"seats": seats}
            if kind == "seat.sync"
            else {"gb": round(tenant.storage_gb * trend * rng.uniform(0.95, 1.05), 2)}
        )
        events.append(
            {
                "transaction_id": f"{kind}_{tenant.external_id}_{day:%Y%m%d}_{hour}",
                "customer_id": tenant.external_id,
                "code": kind,
                "timestamp": at.isoformat(),
                "properties": props,
            }
        )
    return events


def frozen(at: datetime) -> Callable[[], datetime]:
    return lambda: at


async def seed(reset: bool, seed_value: int) -> None:
    configure_logging("WARNING")
    # A longer review window leaves the most recent closes as drafts to explore re-rating.
    settings = get_settings().model_copy(update={"draft_review_hours": 120})
    container = build_container(settings, cache=InMemoryEntitlementCache())
    sessions = container.sessions
    rng = random.Random(seed_value)
    now = datetime.now(UTC)
    today = now.date()
    started = time.perf_counter()

    if reset:
        async with container.engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE invoice_lines, invoices, subscription_phases, subscriptions, "
                    "plan_versions, plans, usage_unique_values, usage_rollups_hourly, "
                    "usage_event_keys, usage_events, billable_metrics, customers CASCADE"
                )
            )
            await conn.execute(text("ALTER SEQUENCE invoice_number_seq RESTART WITH 1001"))

    async with sessions() as session:
        metering = MeteringService(session)
        for metric in METRICS:
            await metering.create(MetricDefinition.model_validate(metric))
        plans = PlanService(session)
        versions: dict[str, Any] = {}
        for plan in PLANS:
            plan_out = await plans.create(PlanCreate.model_validate(plan))
            versions[plan["code"]] = plan_out.versions[0].id
        growth_v2 = PlanTerms.model_validate(
            {
                **PLANS[1]["terms"],
                "charges": [
                    {**c, "price": GROWTH_V2_TOKENS} if c["key"] == "tokens" else c
                    for c in PLANS[1]["terms"]["charges"]
                ],
            }
        )
        v2 = await plans.publish_version("growth", growth_v2)
        growth_v2_id = v2.versions[0].id

    tenants = build_tenants(rng, today)
    async with sessions() as session:
        customers = CustomerService(session)
        for tenant in tenants:
            await customers.create(
                CustomerCreate(
                    external_id=tenant.external_id,
                    name=tenant.name,
                    email=f"billing@{tenant.external_id}.example.com",
                )
            )

    first_day = min(t.start for t in tenants)
    growth_v2_from = today - timedelta(days=60)
    total_events = 0
    day = first_day
    while day <= today:
        clock_at = datetime(day.year, day.month, day.day, 2, 0, tzinfo=UTC)
        clock = lambda at=clock_at: at  # noqa: E731
        await run_close_cycle(sessions, settings, container.renderer, clock=clock)

        async with sessions() as session:
            subs = SubscriptionService(session, container.cache, clock=clock)
            for tenant in tenants:
                if tenant.start == day:
                    plan_version = (
                        growth_v2_id if tenant.plan == "growth" and day >= growth_v2_from else None
                    )
                    created = await subs.create(
                        SubscriptionCreate(
                            customer_id=tenant.external_id,
                            plan_code=None if plan_version else tenant.plan,
                            plan_version_id=plan_version,
                            start_on=day,
                            trial_days=tenant.trial_days,
                        )
                    )
                    tenant.subscription_id = created.id
                if tenant.upgrade and tenant.upgrade[0] == day and tenant.subscription_id:
                    target = (
                        growth_v2_id
                        if tenant.upgrade[1] == "growth"
                        else versions[tenant.upgrade[1]]
                    )
                    await subs.change_plan(
                        tenant.subscription_id, PlanChange(plan_version_id=target, effective_on=day)
                    )
                    tenant.plan = tenant.upgrade[1]
                    tenant.daily_requests *= 2.5
                if tenant.cancel_on and tenant.cancel_on - timedelta(days=10) == day:
                    await subs.cancel(
                        tenant.subscription_id, Cancellation(effective_on=tenant.cancel_on)
                    )

        events = [e for t in tenants for e in day_events(rng, t, day, now)]
        async with sessions() as session:
            ingestion = IngestionService(session, settings, container.cache)
            for start in range(0, len(events), settings.max_batch_size):
                result = await ingestion.ingest(events[start : start + settings.max_batch_size])
                if result.rejected:
                    reasons = {r.error.code for r in result.results if r.error}
                    raise RuntimeError(f"seed events rejected on {day}: {reasons}")
        total_events += len(events)
        if day.day == 1 or day == today:
            print(f"  {day}  events so far: {total_events:,}", flush=True)
        day += timedelta(days=1)

    async with container.engine.connect() as conn:
        drafts = await conn.scalar(text("SELECT count(*) FROM invoices WHERE status = 'draft'"))
        finals = await conn.scalar(text("SELECT count(*) FROM invoices WHERE status = 'finalized'"))
    await container.engine.dispose()
    elapsed = time.perf_counter() - started
    print(
        f"Seeded {len(tenants)} customers, {total_events:,} events, "
        f"{finals} finalized and {drafts} draft invoices in {elapsed:.0f}s"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-reset", action="store_true", help="keep existing data")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    asyncio.run(seed(reset=not args.no_reset, seed_value=args.seed))


if __name__ == "__main__":
    main()
