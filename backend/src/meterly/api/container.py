from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from meterly.billing.render import InvoiceRenderer
from meterly.config import Settings
from meterly.entitlements.cache import EntitlementCache


@dataclass(slots=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis | None
    cache: EntitlementCache
    renderer: InvoiceRenderer
