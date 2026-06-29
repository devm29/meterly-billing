from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from meterly.api.auth import RequireAdmin
from meterly.api.container import Container
from meterly.api.errors import install_error_handlers
from meterly.api.middleware import RequestContextMiddleware
from meterly.api.routes import (
    analytics,
    customers,
    events,
    health,
    invoices,
    metrics,
    plans,
    pricing,
    subscriptions,
)
from meterly.billing.render import InvoiceRenderer
from meterly.config import Settings, get_settings
from meterly.db.session import create_engine, create_session_factory
from meterly.entitlements.cache import EntitlementCache, RedisEntitlementCache
from meterly.log import configure_logging


def build_container(settings: Settings, cache: EntitlementCache | None = None) -> Container:
    engine = create_engine(settings)
    redis: Redis | None = None
    if cache is None:
        redis = Redis.from_url(str(settings.redis_url))
        cache = RedisEntitlementCache(redis)
    return Container(
        settings=settings,
        engine=engine,
        sessions=create_session_factory(engine),
        redis=redis,
        cache=cache,
        renderer=InvoiceRenderer(settings),
    )


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state = container or build_container(settings)
        app.state.container = state
        yield
        if state.redis is not None:
            await state.redis.aclose()
        await state.engine.dispose()

    app = FastAPI(
        title="Meterly",
        version="0.1.0",
        summary="Usage metering and usage-based billing engine",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-api-key", "x-request-id"],
        expose_headers=["x-request-id"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    # These two mix ingest-scoped and admin-scoped routes, so they declare auth per route.
    app.include_router(events.router)
    app.include_router(customers.router)
    for module in (metrics, plans, subscriptions, invoices, analytics, pricing):
        app.include_router(module.router, dependencies=[RequireAdmin])
    return app
