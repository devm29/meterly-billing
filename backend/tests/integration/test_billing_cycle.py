from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import time_machine
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import api_events, bootstrap, ingest, token_events

MARCH = datetime(2026, 3, 1, tzinfo=UTC)


async def _subscribe(client: AsyncClient, start: str = "2026-03-01") -> dict[str, Any]:
    response = await client.post(
        "/v1/subscriptions", json={"customer_id": "acme", "plan_code": "growth", "start_on": start}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _run(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/v1/billing/run")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_period_close_drafts_reprices_and_finalizes(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    with time_machine.travel(MARCH + timedelta(days=10), tick=False) as clock:
        await bootstrap(client)
        await _subscribe(client)
        await ingest(client, api_events("acme", 12_500, MARCH + timedelta(days=9)))
        await ingest(
            client,
            token_events(
                "acme", MARCH + timedelta(days=9), [("sonnet", 120_400), ("haiku", 30_000)]
            ),
        )

        clock.move_to(datetime(2026, 4, 1, 0, 30, tzinfo=UTC))
        assert (await _run(client))["drafted"] == []

        clock.move_to(datetime(2026, 4, 1, 1, 30, tzinfo=UTC))
        run = await _run(client)
        assert len(run["drafted"]) == 1
        assert run["finalized"] == []
        invoice_id = run["drafted"][0]

        invoice = (await client.get(f"/v1/invoices/{invoice_id}")).json()
        amounts = {
            line["charge_key"]: Decimal(line["amount"]["amount"]) for line in invoice["lines"]
        }
        # 11,500 billable after 1,000 free: 10,000 at $0.01 plus 1,500 at $0.002
        assert amounts == {
            "platform": Decimal("49.00"),
            "api_calls": Decimal("103.00"),
            "tokens": Decimal("22.65"),
        }
        assert invoice["status"] == "draft"
        assert invoice["total"]["amount"] == "174.65"
        tokens = next(line for line in invoice["lines"] if line["charge_key"] == "tokens")
        groups = tokens["details"]["groups"]
        assert sum(Decimal(g["amount"]["amount"]) for g in groups) == Decimal("22.65")

        late = await ingest(
            client, api_events("acme", 1, MARCH + timedelta(days=20), prefix="late")
        )
        assert late["results"][0]["error"]["code"] == "period_closed"

        preview = await client.post(
            f"/v1/invoices/{invoice_id}/rerate",
            json={"overrides": {"api_calls": {"model": "per_unit", "unit_price": "0.005"}}},
        )
        diff = preview.json()["diff"]
        assert preview.json()["applied"] is False
        # cheaper calls drop usage spend below the $100 commitment, so a true-up line appears
        assert [line["delta"]["amount"] for line in diff["lines"]] == [
            "0.00",
            "-40.50",
            "0.00",
            "14.85",
        ]
        assert diff["delta"]["amount"] == "-25.65"
        assert (await client.get(f"/v1/invoices/{invoice_id}")).json()["total"][
            "amount"
        ] == "174.65"

        applied = await client.post(
            f"/v1/invoices/{invoice_id}/rerate",
            json={
                "overrides": {"api_calls": {"model": "per_unit", "unit_price": "0.005"}},
                "apply": True,
            },
        )
        assert applied.json()["applied"] is True
        assert (await client.get(f"/v1/invoices/{invoice_id}")).json()["total"][
            "amount"
        ] == "149.00"

        clock.move_to(datetime(2026, 4, 2, 2, 0, tzinfo=UTC))
        run = await _run(client)
        assert run["finalized"] == [invoice_id]
        final = (await client.get(f"/v1/invoices/{invoice_id}")).json()
        assert final["status"] == "finalized"
        assert final["number"] == "MTR-2026-001001"

        rerate = await client.post(
            f"/v1/invoices/{invoice_id}/rerate",
            json={"overrides": {"api_calls": {"model": "per_unit", "unit_price": "0"}}},
        )
        assert rerate.status_code == 409

        pdf = await client.get(f"/v1/invoices/{invoice_id}/pdf")
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")
        html = await client.get(f"/v1/invoices/{invoice_id}/html")
        assert "MTR-2026-001001" in html.text

    with pytest.raises(DBAPIError, match="immutable"):
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE invoices SET total = 0 WHERE id = :id"), {"id": invoice_id}
            )


async def test_minimum_commitment_and_trial(client: AsyncClient) -> None:
    with time_machine.travel(MARCH, tick=False) as clock:
        await bootstrap(client)
        response = await client.post(
            "/v1/subscriptions",
            json={
                "customer_id": "acme",
                "plan_code": "growth",
                "start_on": "2026-03-01",
                "trial_days": 10,
            },
        )
        assert response.json()["status"] == "trialing"
        clock.move_to(MARCH + timedelta(days=20))
        await ingest(client, api_events("acme", 3000, MARCH + timedelta(days=2), prefix="trial"))
        await ingest(client, api_events("acme", 2000, MARCH + timedelta(days=15), prefix="paid"))

        clock.move_to(datetime(2026, 4, 1, 3, 0, tzinfo=UTC))
        invoice_id = (await _run(client))["drafted"][0]
        lines = (await client.get(f"/v1/invoices/{invoice_id}")).json()["lines"]
        by_key = {line["charge_key"]: line for line in lines}
        # trial days are free: 21 of 31 days billed, allowance prorated to 677.42 units
        assert by_key["platform"]["amount"]["amount"] == "33.19"
        assert by_key["api_calls"]["quantity"] == "2000"
        assert by_key["api_calls"]["amount"]["amount"] == "13.23"
        assert by_key["minimum_commitment"]["amount"]["amount"] == "54.51"


async def test_mid_cycle_upgrade_prorates_fixed_fees(client: AsyncClient) -> None:
    with time_machine.travel(MARCH, tick=False) as clock:
        await bootstrap(client)
        scale_terms = {
            "currency": "USD",
            "charges": [
                {
                    "key": "platform",
                    "name": "Platform fee",
                    "price": {"model": "flat", "amount": "199"},
                },
                {
                    "key": "api_calls",
                    "name": "API calls",
                    "metric_code": "api_calls",
                    "price": {"model": "per_unit", "unit_price": "0.001"},
                },
            ],
        }
        scale = await client.post(
            "/v1/plans", json={"code": "scale", "name": "Scale", "terms": scale_terms}
        )
        scale_version = scale.json()["versions"][0]["id"]
        sub = await _subscribe(client)

        clock.move_to(datetime(2026, 3, 11, 9, 0, tzinfo=UTC))
        await ingest(client, api_events("acme", 4000, MARCH + timedelta(days=5), prefix="before"))
        preview = await client.post(
            f"/v1/subscriptions/{sub['id']}/change-plan",
            json={"plan_version_id": scale_version, "dry_run": True},
        )
        proration = preview.json()["proration"]
        assert (proration["days_remaining"], proration["days_in_period"]) == (21, 31)
        assert proration["old_fixed_for_remaining_days"]["amount"] == "33.19"
        assert proration["net_change"]["amount"] == "101.62"

        changed = await client.post(
            f"/v1/subscriptions/{sub['id']}/change-plan", json={"plan_version_id": scale_version}
        )
        assert [p["plan_code"] for p in changed.json()["subscription"]["phases"]] == [
            "growth",
            "scale",
        ]
        clock.move_to(datetime(2026, 3, 25, 9, 0, tzinfo=UTC))
        await ingest(client, api_events("acme", 9000, MARCH + timedelta(days=20), prefix="after"))

        clock.move_to(datetime(2026, 4, 1, 2, 0, tzinfo=UTC))
        invoice_id = (await _run(client))["drafted"][0]
        lines = (await client.get(f"/v1/invoices/{invoice_id}")).json()["lines"]
        fixed = [line["amount"]["amount"] for line in lines if line["kind"] == "fixed"]
        assert fixed == ["15.81", "134.81"]
        scale_calls = next(
            line
            for line in lines
            if line["charge_key"] == "api_calls" and line["phase_start"] == "2026-03-11"
        )
        assert scale_calls["quantity"] == "9000"
