from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from meterly.config import Settings
from meterly.entitlements.cache import RedisEntitlementCache
from tests.integration.conftest import api_events, bootstrap


async def test_routes_require_an_api_key(anonymous_client: AsyncClient) -> None:
    assert (await anonymous_client.get("/healthz")).status_code == 200
    missing = await anonymous_client.get("/v1/plans")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    wrong = await anonymous_client.get("/v1/plans", headers={"x-api-key": "nope"})
    assert wrong.status_code == 401


async def test_ingest_key_cannot_reach_admin_routes(
    client: AsyncClient, ingest_client: AsyncClient
) -> None:
    await bootstrap(client)
    batch = await ingest_client.post(
        "/v1/events/batch",
        json={"events": api_events("acme", 2, datetime.now(UTC) - timedelta(minutes=1))},
    )
    assert batch.status_code == 202
    assert (await ingest_client.get("/v1/customers/acme/entitlements")).status_code == 200
    for method, path in (
        ("GET", "/v1/plans"),
        ("GET", "/v1/events"),
        ("POST", "/v1/billing/run"),
        ("GET", "/v1/customers"),
    ):
        response = await ingest_client.request(method, path)
        assert response.status_code == 403, (path, response.text)


async def test_request_ids_are_echoed_only_when_well_formed(client: AsyncClient) -> None:
    good = await client.get("/healthz", headers={"x-request-id": "trace-123"})
    assert good.headers["x-request-id"] == "trace-123"
    bad = await client.get("/healthz", headers={"x-request-id": "x" * 65})
    assert bad.headers["x-request-id"] != "x" * 65
    assert len(bad.headers["x-request-id"]) == 32


async def test_redis_cache_invalidates_by_generation(settings: Settings) -> None:
    redis = Redis.from_url(str(settings.redis_url))
    try:
        await redis.ping()
    except (RedisConnectionError, OSError):
        await redis.aclose()
        pytest.skip("Redis is not running")
    cache = RedisEntitlementCache(redis, prefix=f"meterly:test:{uuid4().hex}")
    customer, other = uuid4(), uuid4()
    try:
        await cache.set(customer, "api", "first", ttl_seconds=30)
        await cache.set(other, "api", "kept", ttl_seconds=30)
        assert await cache.get(customer, "api") == "first"

        await cache.invalidate([customer])
        assert await cache.get(customer, "api") is None
        assert await cache.get(other, "api") == "kept"

        await cache.set(customer, "api", "second", ttl_seconds=30)
        assert await cache.get(customer, "api") == "second"
        await cache.invalidate([])
    finally:
        await redis.aclose()
