import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import time_machine
from httpx import AsyncClient

from tests.integration.conftest import GROWTH_TERMS, bootstrap

MARCH = datetime(2026, 3, 1, tzinfo=UTC)


def _with_platform_fee(amount: str) -> dict[str, Any]:
    terms = copy.deepcopy(GROWTH_TERMS)
    terms["charges"][0]["price"]["amount"] = amount
    return terms


async def _publish(client: AsyncClient, amount: str) -> str:
    response = await client.post("/v1/plans/growth/versions", json=_with_platform_fee(amount))
    assert response.status_code == 201, response.text
    version_id: str = response.json()["versions"][0]["id"]
    return version_id


async def _subscribe(client: AsyncClient, customer: str = "acme", **extra: Any) -> dict[str, Any]:
    response = await client.post(
        "/v1/subscriptions",
        json={"customer_id": customer, "plan_code": "growth", "start_on": "2026-03-01", **extra},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _change(
    client: AsyncClient, sub_id: str, version: str, on: str, *, status: int = 200
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/subscriptions/{sub_id}/change-plan",
        json={"plan_version_id": version, "effective_on": on},
    )
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def _phases(body: dict[str, Any]) -> list[tuple[int, str, str | None]]:
    return [(p["version"], p["starts_on"], p["ends_on"]) for p in body["phases"]]


async def test_an_earlier_change_replaces_a_later_scheduled_one(client: AsyncClient) -> None:
    with time_machine.travel(MARCH + timedelta(days=4), tick=False) as clock:
        await bootstrap(client)
        sub = await _subscribe(client)
        v2 = await _publish(client, "99")
        v3 = await _publish(client, "199")

        await _change(client, sub["id"], v2, "2026-03-20")
        changed = await _change(client, sub["id"], v3, "2026-03-10")

        assert _phases(changed["subscription"]) == [
            (1, "2026-03-01", "2026-03-10"),
            (3, "2026-03-10", None),
        ]

        clock.move_to(datetime(2026, 4, 1, 3, 0, tzinfo=UTC))
        invoice_id = (await client.post("/v1/billing/run")).json()["drafted"][0]
        lines = (await client.get(f"/v1/invoices/{invoice_id}")).json()["lines"]
        fixed = [line for line in lines if line["kind"] == "fixed"]
        assert [line["amount"]["amount"] for line in fixed] == ["14.23", "141.23"]
        days = sum(Decimal(line["details"]["proration"]) for line in fixed)
        assert abs(days - 1) < Decimal("1e-20")


async def test_switching_back_to_the_current_version_cancels_a_scheduled_change(
    client: AsyncClient,
) -> None:
    with time_machine.travel(MARCH + timedelta(days=4), tick=False):
        await bootstrap(client)
        sub = await _subscribe(client)
        v1 = sub["phases"][0]["plan_version_id"]
        v2 = await _publish(client, "99")

        await _change(client, sub["id"], v2, "2026-03-20")
        reverted = await _change(client, sub["id"], v1, "2026-03-15")

        assert _phases(reverted["subscription"]) == [(1, "2026-03-01", None)]
        await _change(client, sub["id"], v1, "2026-03-16", status=409)


async def test_cancellation_blocks_overlapping_subscriptions_until_it_ends(
    client: AsyncClient,
) -> None:
    with time_machine.travel(MARCH + timedelta(days=4), tick=False):
        await bootstrap(client)
        sub = await _subscribe(client)
        canceled = await client.post(
            f"/v1/subscriptions/{sub['id']}/cancel", json={"effective_on": "2026-04-15"}
        )
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["ends_on"] == "2026-04-15"
        again = await client.post(
            f"/v1/subscriptions/{sub['id']}/cancel", json={"effective_on": "2026-04-20"}
        )
        assert again.status_code == 409

        overlapping = await client.post(
            "/v1/subscriptions",
            json={"customer_id": "acme", "plan_code": "growth", "start_on": "2026-04-10"},
        )
        assert overlapping.status_code == 409
        assert "2026-04-15" in overlapping.json()["error"]["message"]

        follow_on = await client.post(
            "/v1/subscriptions",
            json={"customer_id": "acme", "plan_code": "growth", "start_on": "2026-04-15"},
        )
        assert follow_on.status_code == 201, follow_on.text


async def test_plan_change_invalidates_cached_entitlements(client: AsyncClient) -> None:
    with time_machine.travel(MARCH + timedelta(days=4), tick=False):
        await bootstrap(client)
        terms = copy.deepcopy(GROWTH_TERMS)
        terms["entitlements"] = []
        basic = await client.post(
            "/v1/plans", json={"code": "basic", "name": "Basic", "terms": terms}
        )
        basic_version = basic.json()["versions"][0]["id"]
        sub = await _subscribe(client)

        assert (await client.get("/v1/customers/acme/entitlements/sso")).json()["allowed"]
        assert (await client.get("/v1/customers/acme/entitlements/sso")).json()["cached"]

        await _change(client, sub["id"], basic_version, "2026-03-05")
        after = (await client.get("/v1/customers/acme/entitlements/sso")).json()
        assert (after["allowed"], after["reason"], after["cached"]) == (
            False,
            "not_in_plan",
            False,
        )

        listed = (await client.get("/v1/customers/acme/entitlements")).json()
        assert listed["entitlements"] == []
