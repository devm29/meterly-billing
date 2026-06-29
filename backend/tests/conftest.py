from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import PostgresDsn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from meterly.api.app import build_container, create_app
from meterly.api.container import Container
from meterly.config import DEV_ADMIN_KEY, DEV_INGEST_KEY, Settings
from meterly.entitlements.cache import InMemoryEntitlementCache

BACKEND = Path(__file__).resolve().parents[1]
TEST_DSN = os.environ.get(
    "METERLY_TEST_DATABASE_URL", "postgresql+asyncpg://meterly@localhost:5507/meterly_test"
)
TABLES = (
    "invoice_documents, invoice_lines, invoices, subscription_phases, subscriptions, "
    "plan_versions, plans, usage_unique_values, usage_rollups_hourly, usage_event_keys, "
    "usage_events, billable_metrics, customers"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/" in str(item.path):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        env="test",
        database_url=PostgresDsn(TEST_DSN),
        log_level="WARNING",
        close_grace_minutes=60,
        draft_review_hours=24,
    )


@pytest.fixture(scope="session")
def migrated() -> None:
    env = {**os.environ, "METERLY_DATABASE_URL": TEST_DSN}
    for command in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            cwd=BACKEND,
            env=env,
            check=True,
            capture_output=True,
        )


@pytest.fixture(scope="session")
async def container(settings: Settings, migrated: None) -> AsyncIterator[Container]:
    built = build_container(settings, cache=InMemoryEntitlementCache())
    yield built
    await built.engine.dispose()


@pytest.fixture
def engine(container: Container) -> AsyncEngine:
    return container.engine


@pytest.fixture(autouse=True)
async def clean_database(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    if "integration" not in request.keywords:
        yield
        return
    container: Container = request.getfixturevalue("container")
    async with container.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await conn.execute(text("ALTER SEQUENCE invoice_number_seq RESTART WITH 1001"))
    container.cache = InMemoryEntitlementCache()
    yield


@pytest.fixture
def app(container: Container, settings: Settings) -> FastAPI:
    app = create_app(settings, container)
    app.state.container = container
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with _client(app, DEV_ADMIN_KEY) as http:
        yield http


@pytest.fixture
async def ingest_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with _client(app, DEV_INGEST_KEY) as http:
        yield http


@pytest.fixture
async def anonymous_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with _client(app, None) as http:
        yield http


def _client(app: FastAPI, key: str | None) -> AsyncClient:
    headers = {"x-api-key": key} if key else {}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)
