from datetime import date, timedelta
from decimal import Decimal
from statistics import mean

import pytest

from flightkit import Engine, MemoryCache, Search, TripQuery
from flightkit.adapters.zerolook import FakeZerolook, ZerolookClient
from flightkit.adapters.zerolook.fake import fake_trips

TUESDAY = date(2027, 6, 1)


def _request(**overrides):
    return {
        "orig": "ZRH",
        "dest": "ATH",
        "departDate": "2027-06-01",
        "returnDate": "2027-06-08",
        "pax": 1,
        "cabin": "economy",
        **overrides,
    }


def _cheapest(request) -> float:
    return min(float(t["fareAmt"]) for t in fake_trips(request))


@pytest.fixture
async def client():
    fake = FakeZerolook(chaos=False, latency=(0, 0))
    async with ZerolookClient("https://zerolook.test", "k", transport=fake.transport()) as c:
        yield c, fake


def test_same_request_gives_same_prices():
    first = [t["fareAmt"] for t in fake_trips(_request())]
    again = [t["fareAmt"] for t in fake_trips(_request())]
    assert first == again


def test_destinations_have_different_price_levels():
    assert _cheapest(_request(dest="ATH")) != _cheapest(_request(dest="JTR"))


def test_midweek_is_cheaper_than_weekends_on_average():
    def avg(weekday: int) -> float:
        days = [TUESDAY + timedelta(days=(weekday - 1) % 7 + 7 * w) for w in range(8)]
        return mean(
            _cheapest(_request(dest=d, departDate=day.isoformat(), returnDate=None))
            for d in ["ATH", "HER", "JTR"]
            for day in days
        )

    assert avg(1) < avg(4)  # Tuesday < Friday
    assert avg(2) < avg(6)  # Wednesday < Sunday


def test_more_passengers_and_premium_cabins_cost_more():
    base = _cheapest(_request())
    assert _cheapest(_request(pax=2)) == pytest.approx(base * 2, rel=0.01)
    assert _cheapest(_request(cabin="business")) > base * 2


def test_one_stop_is_cheaper_than_direct():
    trips = fake_trips(_request())
    direct = next(t for t in trips if t["stops"] == 0)
    assert all(float(t["fareAmt"]) < float(direct["fareAmt"]) for t in trips if t["stops"])


async def test_client_parses_fake_responses(client):
    c, fake = client
    search = Search(
        origin="ZRH", destination="ATH", depart_date=TUESDAY, return_date=date(2027, 6, 8)
    )

    trips = await c.search(search)

    assert len(trips) >= 2
    assert all(t.price.currency == "EUR" and t.price.amount > Decimal(0) for t in trips)
    assert all(0.55 <= (t.confidence or 0) <= 0.97 for t in trips)
    assert fake.requests == 1


async def test_without_chaos_nothing_fails(client):
    c, fake = client
    query = TripQuery(
        origin="ZRH", destinations=("ATH", "HER"), depart_from=TUESDAY, depart_to=date(2027, 6, 7)
    )

    result = await Engine(c, cache=MemoryCache()).search_trips(query)

    assert result.failures == ()
    assert fake.errors == 0
    assert result.stats.calls == 14


async def test_chaos_errors_are_absorbed_by_retries():
    fake = FakeZerolook(chaos=True, latency=(0, 0), seed=1)
    query = TripQuery(
        origin="ZRH", destinations=("ATH", "HER"), depart_from=TUESDAY, depart_to=date(2027, 6, 30)
    )
    async with ZerolookClient(
        "https://zerolook.test", "k", transport=fake.transport(), backoff=0, max_retries=3
    ) as c:
        result = await Engine(c).search_trips(query)

    assert fake.errors > 0
    assert fake.requests == result.stats.calls + fake.errors
    assert len(result.failures) == 0


async def test_unknown_path_is_a_404():
    fake = FakeZerolook(chaos=False, latency=(0, 0))
    request = await fake.handle(
        __import__("httpx").Request("GET", "https://zerolook.test/v1/nothing")
    )
    assert request.status_code == 404
