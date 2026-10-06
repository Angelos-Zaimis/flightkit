from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")

import httpx  # noqa: E402

from flightkit.core.engine import Engine  # noqa: E402
from flightkit.entrypoints.api import app  # noqa: E402
from flightkit.models import Price, PricedTrip, Search  # noqa: E402

QUERY = {
    "origin": "zrh",
    "destinations": ["ATH", "HER"],
    "depart_from": "2027-06-01",
    "depart_to": "2027-06-03",
    "min_nights": 7,
    "max_nights": 7,
}


class FakeSource:
    def __init__(self) -> None:
        self.calls: list[Search] = []

    async def search(self, search: Search) -> list[PricedTrip]:
        self.calls.append(search)
        return [
            PricedTrip(
                price=Price(amount="100", currency="EUR"),
                confidence=0.9,
                carrier="LX",
                stops=0,
                deeplink="https://example.com/book",
                fetched_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
                source="prediction",
                search=search,
            )
        ]


@pytest.fixture
def source():
    fake = FakeSource()
    app.state.engine = Engine(fake, max_searches=10)
    return fake


@pytest.fixture
async def client(source):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_trips_returns_results(client, source):
    response = await client.post("/trips", json=QUERY)

    assert response.status_code == 200
    body = response.json()
    eur = body["currencies"]["EUR"]
    assert len(eur["trips"]) == 6
    assert set(eur["cheapest_by_destination"]) == {"ATH", "HER"}
    assert list(eur["calendar"]) == ["2027-06-01", "2027-06-02", "2027-06-03"]
    assert body["failures"] == []
    assert body["stats"] == {
        "searches": 6,
        "cache_hits": 0,
        "coalesced": 0,
        "calls": 6,
        "failures": 0,
    }
    assert len(source.calls) == 6


async def test_too_many_searches_is_a_422_not_a_500(client, source):
    response = await client.post("/trips", json={**QUERY, "depart_to": "2027-06-30"})

    assert response.status_code == 422
    assert response.json() == {"detail": "query expands to 60 searches, limit is 10"}
    assert source.calls == []


async def test_invalid_query_is_rejected_by_the_model(client, source):
    response = await client.post("/trips", json={**QUERY, "destinations": ["ZRH"]})

    assert response.status_code == 422
    assert "origin must not be one of the destinations" in response.text
    assert source.calls == []


async def test_search_endpoint_still_works(client, source):
    response = await client.post(
        "/search", json=[{"origin": "ZRH", "destination": "ATH", "depart_date": "2027-06-01"}]
    )

    assert response.status_code == 200
    assert len(response.json()["trips"]) == 1
