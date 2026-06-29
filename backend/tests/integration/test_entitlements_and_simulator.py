from datetime import UTC, datetime, timedelta

import time_machine
from httpx import AsyncClient

from tests.integration.conftest import api_events, bootstrap, ingest

NOW = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
async def test_entitlement_quota_tracks_usage_and_cache_invalidates(client: AsyncClient) -> None:
    await bootstrap(client)
    await client.post(
        "/v1/subscriptions",
        json={"customer_id": "acme", "plan_code": "growth", "start_on": "2026-05-01"},
    )
    await ingest(client, api_events("acme", 1200, NOW - timedelta(days=2)))

    first = (await client.get("/v1/customers/acme/entitlements/api")).json()
    assert (first["used"], first["remaining"], first["allowed"], first["cached"]) == (
        "1200",
        "48800",
        True,
        False,
    )
    assert (await client.get("/v1/customers/acme/entitlements/api")).json()["cached"] is True

    await ingest(client, api_events("acme", 300, NOW - timedelta(hours=1), prefix="more"))
    fresh = (await client.get("/v1/customers/acme/entitlements/api")).json()
    assert (fresh["used"], fresh["cached"]) == ("1500", False)

    sso = (await client.get("/v1/customers/acme/entitlements/sso")).json()
    assert sso["allowed"] is True
    assert sso["reason"] == "included"
    missing = (await client.get("/v1/customers/acme/entitlements/audit_log")).json()
    assert missing["allowed"] is False
    assert missing["reason"] == "not_in_plan"


@time_machine.travel(NOW, tick=False)
async def test_simulator_replays_usage_through_candidate_pricing(client: AsyncClient) -> None:
    await bootstrap(client)
    await client.post(
        "/v1/subscriptions",
        json={"customer_id": "acme", "plan_code": "growth", "start_on": "2026-05-01"},
    )
    await ingest(client, api_events("acme", 21_000, NOW - timedelta(days=3)))
    candidate = {
        "currency": "USD",
        "charges": [
            {"key": "platform", "name": "Platform", "price": {"model": "flat", "amount": "0"}},
            {
                "key": "calls",
                "name": "Calls",
                "metric_code": "api_calls",
                "price": {"model": "per_unit", "unit_price": "0.004"},
            },
        ],
    }
    response = await client.post(
        "/v1/simulations", json={"customer_id": "acme", "terms": candidate}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    period = body["periods"][-1]
    assert period["in_progress"] is True
    assert period["candidate"]["amount"] == "84.00"
    assert period["actual"]["amount"] == "169.00"
    assert body["delta"]["amount"] == "-85.00"


async def test_validation_errors_are_structured(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/pricing/quote",
        json={
            "price": {"model": "graduated", "tiers": [{"up_to": "10", "unit_price": "1"}]},
            "quantity": "5",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    quote = await client.post(
        "/v1/pricing/quote",
        json={
            "price": {
                "model": "volume",
                "tiers": [
                    {"up_to": "100", "unit_price": "1"},
                    {"up_to": None, "unit_price": "0.5"},
                ],
            },
            "quantity": "150",
        },
    )
    assert quote.json()["amount"]["amount"] == "75.00"
