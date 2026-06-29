import asyncio
from datetime import UTC, datetime, timedelta

import time_machine
from httpx import AsyncClient

from tests.integration.conftest import api_events, bootstrap, ingest, token_events

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
async def test_batch_reports_status_per_item(client: AsyncClient) -> None:
    await bootstrap(client)
    events = api_events("acme", 3, NOW - timedelta(minutes=5))
    events.append(events[0])
    events.append(
        {
            "transaction_id": "x",
            "customer_id": "ghost",
            "code": "api_request",
            "timestamp": NOW.isoformat(),
        }
    )
    events.append(
        {
            "transaction_id": "y",
            "customer_id": "acme",
            "code": "api_request",
            "timestamp": (NOW + timedelta(hours=2)).isoformat(),
        }
    )
    events.append({"customer_id": "acme", "code": "api_request", "timestamp": "yesterday"})
    events.append(
        {
            "transaction_id": "z",
            "customer_id": "acme",
            "code": "llm_completion",
            "timestamp": NOW.isoformat(),
            "properties": {"model": "m"},
        }
    )

    body = await ingest(client, events)

    assert (body["accepted"], body["duplicates"], body["rejected"]) == (4, 1, 3)
    errors = [r["error"]["code"] for r in body["results"] if r["error"]]
    assert errors == ["unknown_customer", "timestamp_in_future", "invalid_event"]
    last = body["results"][-1]
    assert last["status"] == "accepted"
    assert [w["code"] for w in last["warnings"]] == ["missing_property"]


@time_machine.travel(NOW, tick=False)
async def test_missing_property_only_skips_the_metric_that_needs_it(client: AsyncClient) -> None:
    await bootstrap(client)
    events = api_events("acme", 4, NOW - timedelta(minutes=5))
    for event in events[:2]:
        event["properties"] = {}

    body = await ingest(client, events)

    assert body["accepted"] == 4
    assert [len(r["warnings"]) for r in body["results"]] == [1, 1, 0, 0]
    calls = await client.get("/v1/customers/acme/usage", params={"metric": "api_calls", "days": 1})
    users = await client.get(
        "/v1/customers/acme/usage", params={"metric": "active_users", "days": 1}
    )
    assert calls.json()["total"] == "4"
    assert users.json()["total"] == "2"


@time_machine.travel(NOW, tick=False)
async def test_non_object_items_are_rejected_individually(client: AsyncClient) -> None:
    await bootstrap(client)
    events: list[object] = [*api_events("acme", 1, NOW), "nope", 42]
    response = await client.post("/v1/events/batch", json={"events": events})
    assert response.status_code == 202
    body = response.json()
    assert (body["accepted"], body["rejected"]) == (1, 2)
    assert {r["error"]["code"] for r in body["results"][1:]} == {"invalid_event"}


@time_machine.travel(NOW, tick=False)
async def test_replayed_batch_is_idempotent(client: AsyncClient) -> None:
    await bootstrap(client)
    events = api_events("acme", 50, NOW - timedelta(hours=3))
    first = await ingest(client, events)
    second = await ingest(client, events)
    assert first["accepted"] == 50
    assert second["accepted"] == 0
    assert second["duplicates"] == 50
    assert all(r["late"] for r in first["results"])

    usage = await client.get("/v1/customers/acme/usage", params={"metric": "api_calls", "days": 1})
    assert usage.json()["total"] == "50"


@time_machine.travel(NOW, tick=False)
async def test_concurrent_identical_batches_count_once(client: AsyncClient) -> None:
    await bootstrap(client)
    events = api_events("acme", 200, NOW - timedelta(minutes=1))
    results = await asyncio.gather(*(ingest(client, events) for _ in range(4)))
    assert sum(r["accepted"] for r in results) == 200
    reconcile = await client.get(
        "/v1/metrics/api_calls/reconcile",
        params={
            "customer_id": "acme",
            "start": (NOW - timedelta(days=1)).isoformat(),
            "end": (NOW + timedelta(days=1)).isoformat(),
        },
    )
    assert reconcile.json()["from_rollups"] == "200"
    assert reconcile.json()["matches"] is True


@time_machine.travel(NOW, tick=False)
async def test_rollups_agree_with_raw_events_for_every_aggregation(client: AsyncClient) -> None:
    await bootstrap(client)
    spread = [NOW - timedelta(hours=h, minutes=7) for h in range(6)]
    for i, at in enumerate(spread):
        await ingest(client, api_events("acme", 10, at, prefix=f"r{i}", users=4 + i))
        await ingest(
            client, token_events("acme", at, [("sonnet", 1200 + i), ("haiku", 300)], prefix=f"t{i}")
        )
    # a late event for an earlier hour must not override the newer seat count
    await ingest(
        client,
        [
            {
                "transaction_id": "seat-new",
                "customer_id": "acme",
                "code": "seat_sync",
                "timestamp": (NOW - timedelta(minutes=1)).isoformat(),
                "properties": {"seats": 12},
            },
            {
                "transaction_id": "seat-old",
                "customer_id": "acme",
                "code": "seat_sync",
                "timestamp": (NOW - timedelta(hours=5)).isoformat(),
                "properties": {"seats": 40},
            },
        ],
    )

    window = {
        "customer_id": "acme",
        "start": (NOW - timedelta(days=1)).isoformat(),
        "end": (NOW + timedelta(hours=1)).isoformat(),
    }
    expected = {
        "api_calls": "60",
        "tokens": str(sum(1200 + i for i in range(6)) + 1800),
        "seats": "12",
        "active_users": "9",
    }
    for code, value in expected.items():
        body = (await client.get(f"/v1/metrics/{code}/reconcile", params=window)).json()
        assert body["matches"], body
        assert body["from_rollups"] == value, (code, body)

    series = await client.get(
        "/v1/customers/acme/usage",
        params={"metric": "tokens", "days": 1, "granularity": "hour", "by_group": "true"},
    )
    assert series.json()["series"] == ["sonnet", "haiku"]
