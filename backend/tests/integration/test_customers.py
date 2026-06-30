from httpx import AsyncClient


async def _create(client: AsyncClient, external_id: str, name: str) -> None:
    response = await client.post(
        "/v1/customers", json={"external_id": external_id, "name": name, "currency": "USD"}
    )
    assert response.status_code == 201, response.text


async def test_search_treats_like_wildcards_literally(client: AsyncClient) -> None:
    await _create(client, "acme_eu", "Acme Europe")
    await _create(client, "acmexeu", "Acme Export")
    await _create(client, "growth", "Growth 100% Ltd")
    await _create(client, "growth-2", "Growth 1000 Ltd")

    underscore = await client.get("/v1/customers", params={"q": "acme_"})
    percent = await client.get("/v1/customers", params={"q": "100%"})

    assert [c["external_id"] for c in underscore.json()["items"]] == ["acme_eu"]
    assert [c["external_id"] for c in percent.json()["items"]] == ["growth"]
    assert percent.json()["total"] == 1


async def test_search_matches_name_or_external_id_case_insensitively(client: AsyncClient) -> None:
    await _create(client, "northwind", "Northwind Labs")
    await _create(client, "zephyr", "Zephyr Travel")

    by_name = await client.get("/v1/customers", params={"q": "LABS"})
    by_id = await client.get("/v1/customers", params={"q": "zeph"})

    assert [c["external_id"] for c in by_name.json()["items"]] == ["northwind"]
    assert [c["external_id"] for c in by_id.json()["items"]] == ["zephyr"]
