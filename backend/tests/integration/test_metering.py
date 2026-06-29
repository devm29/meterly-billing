from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from meterly.api.container import Container
from meterly.billing.periods import add_months
from meterly.worker.main import ensure_partitions
from tests.integration.conftest import api_events, bootstrap, ingest

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)


def _events(code: str, readings: list[tuple[datetime, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": f"{code}-{i}",
            "customer_id": "acme",
            "code": code,
            "timestamp": at.isoformat(),
            "properties": properties,
        }
        for i, (at, properties) in enumerate(readings)
    ]


async def _total(client: AsyncClient, metric: str, *, customer: bool = False) -> str:
    path = "/v1/customers/acme/usage" if customer else f"/v1/metrics/{metric}/usage"
    params: dict[str, str | int] = {"days": 7}
    if customer:
        params["metric"] = metric
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    total: str = response.json()["total"]
    return total


@time_machine.travel(NOW, tick=False)
async def test_series_totals_combine_the_way_each_aggregation_does(client: AsyncClient) -> None:
    await bootstrap(client)
    created = await client.post(
        "/v1/metrics",
        json={
            "code": "peak_connections",
            "name": "Peak connections",
            "event_code": "connections",
            "aggregation": "max",
            "field": "open",
        },
    )
    assert created.status_code == 201, created.text
    days = [NOW - timedelta(days=d, hours=1) for d in range(4)]
    await ingest(client, _events("connections", [(at, {"open": 10}) for at in days]))
    await ingest(client, api_events("acme", 6, days[0], prefix="today"))
    await ingest(client, api_events("acme", 6, days[1], prefix="yesterday"))
    await ingest(client, _events("seat_sync", [(days[2], {"seats": 5}), (days[0], {"seats": 7})]))

    assert await _total(client, "peak_connections") == "10"
    assert await _total(client, "active_users") == "3"
    assert await _total(client, "seats") == "7"
    assert await _total(client, "api_calls") == "12"
    assert await _total(client, "peak_connections", customer=True) == "10"
    assert await _total(client, "active_users", customer=True) == "3"


@time_machine.travel(NOW, tick=False)
async def test_new_metric_backfills_rollups_from_the_event_log(client: AsyncClient) -> None:
    await bootstrap(client)
    await ingest(client, _events("export", [(HOUR - timedelta(hours=h), {}) for h in range(10)]))

    created = await client.post(
        "/v1/metrics",
        json={"code": "exports", "name": "Exports", "event_code": "export", "aggregation": "count"},
    )
    assert created.status_code == 201, created.text

    reconcile = await client.get(
        "/v1/metrics/exports/reconcile",
        params={
            "customer_id": "acme",
            "start": (HOUR - timedelta(days=1)).isoformat(),
            "end": (HOUR + timedelta(hours=1)).isoformat(),
        },
    )
    body = reconcile.json()
    assert (body["from_rollups"], body["from_raw_events"], body["matches"]) == ("10", "10", True)


@time_machine.travel(NOW, tick=False)
async def test_reconcile_validates_its_window(client: AsyncClient) -> None:
    await bootstrap(client)
    for start, end in (
        (NOW - timedelta(minutes=30), NOW + timedelta(hours=1)),
        (HOUR, HOUR - timedelta(hours=1)),
        (HOUR - timedelta(days=500), HOUR),
    ):
        response = await client.get(
            "/v1/metrics/api_calls/reconcile",
            params={"customer_id": "acme", "start": start.isoformat(), "end": end.isoformat()},
        )
        assert response.status_code == 422, (start, end, response.text)


@time_machine.travel(NOW, tick=False)
async def test_event_log_pages_with_opaque_cursors(client: AsyncClient) -> None:
    await bootstrap(client)
    await ingest(
        client,
        [
            {**event, "timestamp": (NOW - timedelta(minutes=i)).isoformat()}
            for i, event in enumerate(api_events("acme", 5, NOW))
        ],
    )

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/v1/events", params=params)).json()
        seen += [item["transaction_id"] for item in page["items"]]
        assert {item["customer_id"] for item in page["items"]} <= {"acme"}
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"req-{i}" for i in range(5)]

    for bad in ("garbage", "!!!", "MjAyNnxub3QtYS11dWlk"):
        response = await client.get("/v1/events", params={"cursor": bad})
        assert response.status_code == 422, bad
        assert response.json()["error"]["message"] == "invalid cursor"


async def test_event_partitions_are_bounded_in_utc(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS usage_events_y2031m01"))
        await conn.execute(text("SET LOCAL TIME ZONE 'America/New_York'"))
        await conn.execute(text("SELECT meterly_ensure_event_partitions('2031-01-01', 1)"))
        await conn.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        bound = await conn.scalar(
            text(
                "SELECT pg_get_expr(relpartbound, oid) FROM pg_class"
                " WHERE relname = 'usage_events_y2031m01'"
            )
        )
        await conn.execute(text("DROP TABLE usage_events_y2031m01"))
    assert bound == ("FOR VALUES FROM ('2031-01-01 00:00:00+00') TO ('2031-02-01 00:00:00+00')")


async def test_worker_keeps_partitions_ahead(container: Container) -> None:
    await ensure_partitions({"sessions": container.sessions})
    month = add_months(datetime.now(UTC).date().replace(day=1), 4)
    async with container.engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT to_regclass(:name) IS NOT NULL"),
            {"name": f"usage_events_y{month:%Y}m{month:%m}"},
        )
    assert exists is True
