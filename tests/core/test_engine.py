import asyncio
from datetime import date, datetime, timezone

from flightkit.core.engine import Engine
from flightkit.models import Price, PricedTrip, Search


def _search(destination: str) -> Search:
    return Search(origin="ATH", destination=destination, depart_date=date(2026, 10, 1))


def _trip(search: Search, carrier: str = "LX") -> PricedTrip:
    return PricedTrip(
        price=Price(amount="100", currency="EUR"),
        confidence=0.9,
        carrier=carrier,
        stops=0,
        deeplink="https://example.com/book",
        fetched_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        source="prediction",
        search=search,
    )


class FakeSource:
    """Returns one trip per search and records how many ran at once."""

    def __init__(self, delay: float = 0.01) -> None:
        self.delay = delay
        self.calls: list[Search] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def search(self, search: Search) -> list[PricedTrip]:
        self.calls.append(search)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return [_trip(search)]
        finally:
            self.in_flight -= 1


async def test_returns_trips_from_every_search_in_order():
    searches = [_search(d) for d in ["ZRH", "LHR", "CDG"]]

    trips = await Engine(FakeSource()).search_many(searches)

    assert [t.search.destination for t in trips] == ["ZRH", "LHR", "CDG"]


async def test_flattens_multiple_trips_per_search():
    class TwoTrips(FakeSource):
        async def search(self, search: Search) -> list[PricedTrip]:
            return [_trip(search, "LX"), _trip(search, "A3")]

    trips = await Engine(TwoTrips()).search_many([_search("ZRH"), _search("LHR")])

    assert [t.carrier for t in trips] == ["LX", "A3", "LX", "A3"]


async def test_no_searches_makes_no_calls():
    source = FakeSource()
    assert await Engine(source).search_many([]) == []
    assert source.calls == []


async def test_sends_each_search_to_the_source():
    source = FakeSource()
    searches = [_search(d) for d in ["ZRH", "LHR"]]

    await Engine(source).search_many(searches)

    assert source.calls == searches


async def test_searches_run_concurrently():
    source = FakeSource()

    await Engine(source).search_many([_search(d) for d in ["ZRH", "LHR", "CDG", "FRA", "MAD"]])

    assert source.max_in_flight == 5
