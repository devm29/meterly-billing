import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import GROWTH_TERMS, api_events, bootstrap, ingest

MARCH = datetime(2026, 3, 1, tzinfo=UTC)
CLOSE_TIME = datetime(2026, 4, 1, 3, 0, tzinfo=UTC)


async def _subscribe(client: AsyncClient, customer: str, plan: str) -> str:
    response = await client.post(
        "/v1/subscriptions",
        json={"customer_id": customer, "plan_code": plan, "start_on": "2026-03-01"},
    )
    assert response.status_code == 201, response.text
    sub_id: str = response.json()["id"]
    return sub_id


async def _run(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/v1/billing/run")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _draft(client: AsyncClient) -> str:
    with time_machine.travel(MARCH + timedelta(days=2), tick=False) as clock:
        await bootstrap(client)
        await _subscribe(client, "acme", "growth")
        await ingest(client, api_events("acme", 2000, MARCH + timedelta(days=1)))
        clock.move_to(CLOSE_TIME)
        invoice_id: str = (await _run(client))["drafted"][0]
        return invoice_id


async def test_one_failing_subscription_does_not_stall_the_cycle(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    with time_machine.travel(MARCH + timedelta(days=2), tick=False) as clock:
        await bootstrap(client)
        seat_terms = copy.deepcopy(GROWTH_TERMS)
        seat_terms["charges"] = [
            {
                "key": "seats",
                "name": "Seats",
                "metric_code": "seats",
                "price": {"model": "per_unit", "unit_price": "10"},
            }
        ]
        seat_terms["entitlements"] = []
        created = await client.post(
            "/v1/plans", json={"code": "seats", "name": "Seats", "terms": seat_terms}
        )
        assert created.status_code == 201, created.text
        await client.post("/v1/customers", json={"external_id": "broken", "name": "Broken"})
        broken = await _subscribe(client, "broken", "seats")
        await _subscribe(client, "acme", "growth")
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM billable_metrics WHERE code = 'seats'"))

        clock.move_to(CLOSE_TIME)
        first = await _run(client)
        assert len(first["drafted"]) == 1
        assert first["failed_subscriptions"] == [broken]

        async with engine.connect() as conn:
            attempts, error, retry_at = (
                await conn.execute(
                    text(
                        "SELECT close_attempts, last_close_error, next_close_attempt_at"
                        " FROM subscriptions WHERE id = :id"
                    ),
                    {"id": broken},
                )
            ).one()
        assert attempts == 1
        assert "unknown metrics" in error
        assert retry_at > CLOSE_TIME

        second = await _run(client)
        assert second["drafted"] == second["failed_subscriptions"] == []

        clock.move_to(CLOSE_TIME + timedelta(days=1, minutes=5))
        third = await _run(client)
        assert third["failed_subscriptions"] == [broken]
        assert len(third["finalized"]) == 1


@pytest.mark.parametrize(
    ("charge", "override"),
    [
        ("platform", {"model": "per_unit", "unit_price": "1"}),
        ("api_calls", {"model": "flat", "amount": "10"}),
    ],
)
async def test_rerate_rejects_an_override_of_the_other_charge_kind(
    client: AsyncClient, charge: str, override: dict[str, str]
) -> None:
    invoice_id = await _draft(client)
    response = await client.post(
        f"/v1/invoices/{invoice_id}/rerate", json={"overrides": {charge: override}}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "charge_kind_mismatch"


async def test_only_draft_invoices_can_be_deleted(client: AsyncClient, engine: AsyncEngine) -> None:
    with time_machine.travel(MARCH + timedelta(days=2), tick=False) as clock:
        await bootstrap(client)
        await client.post("/v1/customers", json={"external_id": "beta", "name": "Beta"})
        await _subscribe(client, "acme", "growth")
        await _subscribe(client, "beta", "growth")
        clock.move_to(CLOSE_TIME)
        finalized, draft = (await _run(client))["drafted"]
        assert (await client.post(f"/v1/invoices/{finalized}/finalize")).status_code == 200

    with pytest.raises(DBAPIError, match="cannot be deleted"):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM invoices WHERE id = :id"), {"id": finalized})

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM invoices WHERE id = :id"), {"id": draft})
        orphans = await conn.scalar(
            text("SELECT count(*) FROM invoice_lines WHERE invoice_id = :id"), {"id": draft}
        )
    assert orphans == 0


async def test_finalized_invoice_pdf_is_stored_after_finalization(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    draft = await _draft(client)
    with time_machine.travel(CLOSE_TIME, tick=False):
        finalized = await client.post(f"/v1/invoices/{draft}/finalize")
    assert finalized.status_code == 200
    async with engine.connect() as conn:
        stored = await conn.scalar(
            text("SELECT content FROM invoice_documents WHERE invoice_id = :id"), {"id": draft}
        )
    assert stored is not None
    assert bytes(stored).startswith(b"%PDF")
    pdf = await client.get(f"/v1/invoices/{draft}/pdf")
    assert pdf.content == bytes(stored)
