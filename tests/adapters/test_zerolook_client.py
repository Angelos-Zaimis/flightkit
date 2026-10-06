import asyncio
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from flightkit.adapters.zerolook import ZerolookClient
from flightkit.models import PricedTrip, Search

BASE_URL = "https://zerolook.test"
SEARCH = Search(origin="ATH", destination="ZRH", depart_date=date(2026, 10, 1))
TRIP = {
    "fareAmt": "129.99",
    "cur": "eur",
    "airline": " LX",
    "conf": 0.87,
    "stops": 0,
    "url": "https://example.com/book/123",
    "ts": "2026-09-23T10:00:00Z",
}


@pytest.fixture
async def client():
    async with ZerolookClient(BASE_URL, "secret-key") as c:
        yield c


@pytest.fixture
def zerolook():
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        yield mock


async def test_search_returns_priced_trips(client, zerolook):
    zerolook.post("/v1/search").respond(json={"trips": [TRIP, {**TRIP, "airline": "A3"}]})

    trips = await client.search(SEARCH)

    assert [t.carrier for t in trips] == ["LX", "A3"]
    assert all(isinstance(t, PricedTrip) for t in trips)
    assert trips[0].price.amount == Decimal("129.99")
    assert trips[0].search == SEARCH


async def test_empty_result(client, zerolook):
    zerolook.post("/v1/search").respond(json={"trips": []})
    assert await client.search(SEARCH) == []


async def test_sends_payload_and_auth_header(client, zerolook):
    route = zerolook.post("/v1/search").respond(json={"trips": []})

    await client.search(SEARCH)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert json.loads(request.content) == {
        "orig": "ATH",
        "dest": "ZRH",
        "departDate": "2026-10-01",
        "pax": 1,
        "cabin": "economy",
    }


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
async def test_error_status_raises(client, zerolook, status):
    zerolook.post("/v1/search").respond(status_code=status)
    with pytest.raises(httpx.HTTPStatusError):
        await client.search(SEARCH)


async def test_timeout_raises(client, zerolook):
    zerolook.post("/v1/search").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.TimeoutException):
        await client.search(SEARCH)


async def test_concurrent_searches_share_one_client(client, zerolook):
    route = zerolook.post("/v1/search").respond(json={"trips": [TRIP]})

    results = await asyncio.gather(*(client.search(SEARCH) for _ in range(20)))

    assert len(results) == 20
    assert route.call_count == 20


async def test_async_with_closes_connections():
    async with ZerolookClient(BASE_URL, "k") as c:
        assert not c._http.is_closed
    assert c._http.is_closed
