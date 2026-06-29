from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis


class EntitlementCache(Protocol):
    async def get(self, customer_id: UUID, key: str) -> str | None: ...

    async def set(self, customer_id: UUID, key: str, value: str, ttl_seconds: int) -> None: ...

    async def invalidate(self, customer_ids: Sequence[UUID]) -> None: ...


class RedisEntitlementCache:
    """Entries are namespaced by a per-customer generation counter.

    Invalidation is a single INCR per customer: old entries become unreachable at once and
    simply age out through their TTL, so no key scans are ever needed.
    """

    def __init__(self, redis: Redis, prefix: str = "meterly:ent") -> None:
        self._redis = redis
        self._prefix = prefix

    def _generation_key(self, customer_id: UUID) -> str:
        return f"{self._prefix}:gen:{customer_id}"

    async def _entry_key(self, customer_id: UUID, key: str) -> str:
        generation = await self._redis.get(self._generation_key(customer_id))
        gen = generation.decode() if isinstance(generation, bytes) else (generation or "0")
        return f"{self._prefix}:{customer_id}:{gen}:{key}"

    async def get(self, customer_id: UUID, key: str) -> str | None:
        value = await self._redis.get(await self._entry_key(customer_id, key))
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, customer_id: UUID, key: str, value: str, ttl_seconds: int) -> None:
        await self._redis.set(await self._entry_key(customer_id, key), value, ex=ttl_seconds)

    async def invalidate(self, customer_ids: Sequence[UUID]) -> None:
        if not customer_ids:
            return
        async with self._redis.pipeline(transaction=False) as pipe:
            for customer_id in customer_ids:
                pipe.incr(self._generation_key(customer_id))
            await pipe.execute()


class InMemoryEntitlementCache:
    def __init__(self) -> None:
        self._data: dict[tuple[UUID, str], str] = {}

    async def get(self, customer_id: UUID, key: str) -> str | None:
        return self._data.get((customer_id, key))

    async def set(self, customer_id: UUID, key: str, value: str, ttl_seconds: int) -> None:
        self._data[(customer_id, key)] = value

    async def invalidate(self, customer_ids: Sequence[UUID]) -> None:
        targets = set(customer_ids)
        for entry in [k for k in self._data if k[0] in targets]:
            del self._data[entry]
