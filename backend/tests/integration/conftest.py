from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from httpx import AsyncClient

GROWTH_TERMS: dict[str, Any] = {
    "currency": "USD",
    "minimum_commitment": "100",
    "charges": [
        {"key": "platform", "name": "Platform fee", "price": {"model": "flat", "amount": "49"}},
        {
            "key": "api_calls",
            "name": "API calls",
            "metric_code": "api_calls",
            "price": {
                "model": "graduated",
                "free_units": "1000",
                "tiers": [
                    {"up_to": "10000", "unit_price": "0.01"},
                    {"up_to": None, "unit_price": "0.002"},
                ],
            },
        },
        {
            "key": "tokens",
            "name": "LLM tokens",
            "metric_code": "tokens",
            "price": {"model": "package", "package_size": "1000", "package_price": "0.15"},
        },
    ],
    "entitlements": [
        {"feature": "api", "name": "API access", "metric_code": "api_calls", "limit": "50000"},
        {"feature": "sso", "name": "Single sign-on"},
    ],
}


async def bootstrap(client: AsyncClient, customer: str = "acme") -> None:
    for metric in (
        {
            "code": "api_calls",
            "name": "API calls",
            "event_code": "api_request",
            "aggregation": "count",
        },
        {
            "code": "tokens",
            "name": "Tokens",
            "event_code": "llm_completion",
            "aggregation": "sum",
            "field": "usage.total_tokens",
            "group_by": ["model"],
        },
        {
            "code": "seats",
            "name": "Seats",
            "event_code": "seat_sync",
            "aggregation": "latest",
            "field": "seats",
        },
        {
            "code": "active_users",
            "name": "Active users",
            "event_code": "api_request",
            "aggregation": "unique_count",
            "field": "user_id",
        },
    ):
        response = await client.post("/v1/metrics", json=metric)
        assert response.status_code == 201, response.text
    response = await client.post(
        "/v1/plans", json={"code": "growth", "name": "Growth", "terms": GROWTH_TERMS}
    )
    assert response.status_code == 201, response.text
    response = await client.post(
        "/v1/customers", json={"external_id": customer, "name": "Acme Corp", "currency": "USD"}
    )
    assert response.status_code == 201, response.text


def api_events(
    customer: str, count: int, at: datetime, prefix: str = "req", users: int = 3
) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": f"{prefix}-{i}",
            "customer_id": customer,
            "code": "api_request",
            "timestamp": at.isoformat(),
            "properties": {"user_id": f"u{i % users}"},
        }
        for i in range(count)
    ]


def token_events(
    customer: str, at: datetime, spec: Sequence[tuple[str, int]], prefix: str = "llm"
) -> list[dict[str, Any]]:
    return [
        {
            "transaction_id": f"{prefix}-{i}",
            "customer_id": customer,
            "code": "llm_completion",
            "timestamp": at.isoformat(),
            "properties": {"model": model, "usage": {"total_tokens": tokens}},
        }
        for i, (model, tokens) in enumerate(spec)
    ]


async def ingest(client: AsyncClient, events: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {"accepted": 0, "duplicates": 0, "rejected": 0, "results": []}
    for start in range(0, len(events), 1000):
        response = await client.post(
            "/v1/events/batch", json={"events": events[start : start + 1000]}
        )
        assert response.status_code == 202, response.text
        body = response.json()
        for key in ("accepted", "duplicates", "rejected"):
            merged[key] += body[key]
        merged["results"].extend(body["results"])
    return merged
