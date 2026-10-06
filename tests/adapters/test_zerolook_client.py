import asyncio
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from flightkit.adapters.zerolook import ZerolookClient
from flightkit.adapters.zerolook.client import MAX_DELAY, _retry_after_seconds
from flightkit.errors import (
    AuthenticationError,
    FlightkitError,
    InvalidResponseError,
    ProviderError,
    ProviderStatusError,
    ProviderUnavailableError,
    RateLimitedError,
)
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
    async with ZerolookClient(BASE_URL, "secret-key", backoff=0) as c:
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


@pytest.mark.parametrize(
    ("status", "error", "retryable"),
    [
        (400, ProviderStatusError, False),
        (401, AuthenticationError, False),
        (403, AuthenticationError, False),
        (404, ProviderStatusError, False),
        (429, RateLimitedError, True),
        (500, ProviderStatusError, True),
        (503, ProviderStatusError, True),
    ],
)
async def test_error_status_becomes_a_flightkit_error(client, zerolook, status, error, retryable):
    zerolook.post("/v1/search").respond(status_code=status)

    with pytest.raises(error) as exc:
        await client.search(SEARCH)

    assert type(exc.value) is error
    assert exc.value.status_code == status
    assert exc.value.retryable is retryable
    assert exc.value.provider == "zerolook"
    assert str(exc.value) == f"Zerolook returned HTTP {status}"


async def test_timeout_becomes_provider_unavailable(client, zerolook):
    zerolook.post("/v1/search").mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(ProviderUnavailableError) as exc:
        await client.search(SEARCH)

    assert exc.value.retryable is True
    assert isinstance(exc.value.__cause__, httpx.ReadTimeout)


async def test_concurrent_searches_share_one_client(client, zerolook):
    route = zerolook.post("/v1/search").respond(json={"trips": [TRIP]})

    results = await asyncio.gather(*(client.search(SEARCH) for _ in range(20)))

    assert len(results) == 20
    assert route.call_count == 20


async def test_async_with_closes_connections():
    async with ZerolookClient(BASE_URL, "k") as c:
        assert not c._http.is_closed
    assert c._http.is_closed


async def test_retries_then_succeeds(client, zerolook):
    route = zerolook.post("/v1/search").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"trips": [TRIP]}),
        ]
    )

    trips = await client.search(SEARCH)

    assert len(trips) == 1
    assert route.call_count == 3


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_retryable_status_gives_up_after_max_retries(client, zerolook, status):
    route = zerolook.post("/v1/search").respond(status_code=status)

    with pytest.raises(ProviderStatusError):
        await client.search(SEARCH)

    assert route.call_count == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retried(client, zerolook, status):
    route = zerolook.post("/v1/search").respond(status_code=status)

    with pytest.raises(ProviderStatusError):
        await client.search(SEARCH)

    assert route.call_count == 1


async def test_network_errors_give_up_after_max_retries(client, zerolook):
    route = zerolook.post("/v1/search").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(ProviderUnavailableError):
        await client.search(SEARCH)

    assert route.call_count == 3


@pytest.mark.parametrize("max_retries", [0, 1, 4])
async def test_max_retries_controls_attempts(zerolook, max_retries):
    route = zerolook.post("/v1/search").respond(status_code=503)

    async with ZerolookClient(BASE_URL, "k", max_retries=max_retries, backoff=0) as c:
        with pytest.raises(ProviderStatusError):
            await c.search(SEARCH)

    assert route.call_count == max_retries + 1


async def test_retry_after_header_is_used(client, zerolook, monkeypatch):
    seen = []
    monkeypatch.setattr(
        client, "_delay", lambda attempt, retry_after: seen.append(retry_after) or 0
    )
    zerolook.post("/v1/search").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json={"trips": []}),
        ]
    )

    await client.search(SEARCH)

    assert seen == [3.0]


async def test_retry_after_is_capped():
    async with ZerolookClient(BASE_URL, "k") as c:
        assert c._delay(0, retry_after=3.0) == 3.0
        assert c._delay(0, retry_after=999.0) == MAX_DELAY


@pytest.mark.parametrize("attempt", [0, 1, 2, 3, 10])
async def test_backoff_grows_but_stays_capped(attempt):
    async with ZerolookClient(BASE_URL, "k", backoff=0.5) as c:
        ceiling = min(MAX_DELAY, 0.5 * 2**attempt)
        delays = [c._delay(attempt, retry_after=None) for _ in range(200)]

    assert all(0 <= d <= ceiling for d in delays)
    assert len(set(delays)) > 1  # jittered, not a fixed wait


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "2"}, 2.0),
        ({"Retry-After": "-5"}, 0.0),
        ({"Retry-After": "soon"}, None),
        ({}, None),
    ],
)
def test_retry_after_parsing(headers, expected):
    assert _retry_after_seconds(httpx.Response(429, headers=headers)) == expected


async def test_rate_limit_keeps_retry_after(client, zerolook):
    zerolook.post("/v1/search").respond(429, headers={"Retry-After": "0"})

    with pytest.raises(RateLimitedError) as exc:
        await client.search(SEARCH)

    assert exc.value.retry_after == 0.0


@pytest.mark.parametrize(
    ("response", "cause"),
    [
        (httpx.Response(200, content=b"<html>maintenance</html>"), ValueError),
        (httpx.Response(200, json={"results": []}), KeyError),
        (httpx.Response(200, json=[TRIP]), TypeError),
        (httpx.Response(200, json={"trips": [{**TRIP, "fareAmt": "free"}]}), ValueError),
        (httpx.Response(200, json={"trips": [{**TRIP, "conf": 1.5}]}), ValueError),
    ],
    ids=["not-json", "missing-trips", "wrong-shape", "bad-field", "breaks-domain-rule"],
)
async def test_unexpected_response_becomes_invalid_response(client, zerolook, response, cause):
    zerolook.post("/v1/search").mock(return_value=response)

    with pytest.raises(InvalidResponseError) as exc:
        await client.search(SEARCH)

    assert exc.value.retryable is False
    assert isinstance(exc.value.__cause__, cause)


async def test_every_provider_failure_is_a_flightkit_error(client, zerolook):
    for side_effect in [httpx.ConnectError("x"), httpx.Response(401), httpx.Response(200, json={})]:
        zerolook.post("/v1/search").mock(side_effect=[side_effect] * 3)
        with pytest.raises(ProviderError) as exc:
            await client.search(SEARCH)
        assert isinstance(exc.value, FlightkitError)


async def test_no_httpx_error_escapes(client, zerolook):
    for side_effect in [httpx.ConnectError("x"), httpx.ReadTimeout("x"), httpx.Response(500)]:
        zerolook.post("/v1/search").mock(side_effect=[side_effect] * 3)
        try:
            await client.search(SEARCH)
        except httpx.HTTPError:
            pytest.fail(f"httpx error escaped for {side_effect!r}")
        except FlightkitError:
            pass
